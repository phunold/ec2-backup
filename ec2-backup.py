#!/usr/bin/env python

import os
import subprocess
from subprocess import PIPE
import sys
# FIXME catch ImportError: No module named boto.ec2
import boto.ec2
import optparse
import time

# global settings
# 
# Availablity Zone and region
region = 'us-east-1'
zone = region + 'a'

# devices and disks
# for more information about disk visit:
# https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/block-device-mapping-concepts.html
#
# we found that /dev/sdh persistently becomes /dev/xvdh
# 
ebs_device = '/dev/sdh'  # block device when attaching volume
device     = '/dev/xvdh' # block device when available to server 
mountpoint = '/backup'   # directory only required for rsync

# Ubuntu 12.04 LTS AMD64 EBS
# http://cloud-images.ubuntu.com/locator/ec2/ 
ami = 'ami-00615068'
ssh_user = 'ubuntu'

def exec_remote(login, remote_command):
  # login contains 'ssh_user@ec2.host.amazon.com'
  # -t simulate terminal required for sudo ???
  # FIXME
  # StrictHostKeyChecking maybe delegate to user 
  # and make it part of EC2_BACKUP_FLAGS_SSH
  command_list = ['ssh','-t','-o','StrictHostKeyChecking=no']

  print 'remote_command', remote_command
  print 'login string', login

  # get additional ssh options from environment and append to comamnd_list
  if 'EC2_BACKUP_FLAGS_SSH' in os.environ:
    command_list.extend(os.environ['EC2_BACKUP_FLAGS_SSH'].split())

  # add login user@target and the remote command to execute
  command_list.append(login) # single string
  command_list.extend(remote_command.split()) # multiple strings potentially

  print 'Command list:', command_list

  # Popen expects a list of arguments
  ssh = subprocess.Popen(command_list, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

  # Test result
  result = ssh.stdout.readlines()
  if result == []:
     error = ssh.stderr.readlines()
     print >>sys.stderr, "ERROR: %s" % error
     return False
  else:
     print result
     return True

def connect_ec2(region):
  # Connect to EC2
  # print boto.config.__dict__
  # check if credentials setup
  # boto.exception.NoAuthHandlerFound: No handler was ready to authenticate. 1 handlers were checked. ['QuerySignatureV2AuthHandler'] Check your credentials
  try:
    connection = boto.ec2.connect_to_region(region)
  except boto.exception.NoAuthHandlerFound:
    print "Could not authenticate to ec2!"
    print "run 'aws configure' or setup EC2 keys"
    sys.exit(1)
  
  # connect_to_region return None if region is unkown or incorrect
  if not connection:
    print 'Wrong or unknown region:', region
    sys.exit(1)

  return connection
  
def create_ec2_instance(connection,ami):
  # FIXME key needs to be default or from ENV
  reservations = connection.run_instances(ami,key_name='pstam-keypair')
  # print instance.__dict__
  # ['RunInstancesResponse', 'region', 'instances', 'connection', 'requestId', 'groups', 'id', 'owner_id']
  instance = reservations.instances[0] 
  status = instance.update()
  while status == 'pending':
    print 'Waiting for instance to be ready:', status
    time.sleep(5)
    status = instance.update()
  
  # add EC2 Tagname
  instance.add_tag('Name', 'EC2-Backup Helper Instance')

  # return the freshly create instance object
  return instance

# calculate the volume size
def estimate_size(path):
  # du displays error about folders it cannot read
  # solution is to create /dev/null device from os
  # refernce: http://stackoverflow.com/questions/14023566/prevent-subprocess-popen-from-displaying-output-in-python
  devnull = open(os.devnull, 'wb')
  # run 'du' command
  # --block-size=SIZE allows to automatically get the ceiling size in GB
  proc = subprocess.Popen(['du','--summarize', '--block-size=G', path], stdout=PIPE, stderr=devnull)
  # example output: 2G<tab>/var 
  # proc.stdout is a file descriptor and requires readline
  # [:-1] returns everything but the last character, here it drops the G
  return proc.stdout.readline().split()[0][:-1]
  
def Main():

  # 
  # parse options
  # 
  
  defaults = {'method': 'dd', 'volumeid': None}

  usage = "%prog [-h] [-m method] [-v volume-id] dir"
  description = "ec2-backup -- backup a directory into Elastic Block Storage (EBS)"

  parser = optparse.OptionParser(usage=usage, description=description)

  parser.add_option('-m', '--method',
                    dest="method",
                    choices=['dd', 'rsync'],
                    default=defaults['method'],
                    help='backup method [%default]')

  parser.add_option('-v', '--volume-id',
                    type='string', dest="volumeid",
                    default=defaults['volumeid'],
                    help='EBS volume-id (%default)')

  options, args = parser.parse_args()

  # Check if Directory was set
  if len(args) < 1:
	parser.error('missing directory.')
   
  # print if DEBUG
  print 'method    :', options.method
  print 'volumeid  :', options.volumeid
  print 'remaining :', args

  # 
  # additional validation on the directory 
  # 
  backupdir = args[0]

  if not os.path.exists(backupdir):
    parser.error('directory does not exist: %s' % backupdir)

  if not os.path.isdir(backupdir):
    parser.error('not a directory: %s' % backupdir )

  # 
  # calculate size of directory in GB
  # 
  size = estimate_size(backupdir)
  print 'Estimate Directory size in GB: %s' % size

  #
  # run new EC2 instance 
  # 
  connection = connect_ec2(region)

  instance = create_ec2_instance(connection, ami)

  # 
  # Prepare EBS Volume
  #  

  # create or get EBS volume
  if options.volumeid:
    # FIXME check if volume actually exists
    volume = connection.get_all_volumes([vol.id])[0]
  else:
    volume = connection.create_volume(size, zone)
    print 'Creating volume (size/zone): (%s/%s)', size, zone

  status = volume.update()
  while status == 'creating':
    print 'Waiting for volume to be ready:', status
    time.sleep(5)
    status = volume.update()

  # attach volume to new instance
  # FIXME just prints "attaching" what does that mean, ok? or nok? 
  # ebs_device looks like this: '/dev/sdh' but will become /dev/xvdh on EC2 HVM
  print connection.attach_volume(volume.id, instance.id, ebs_device)

  #
  # SSH/TAR/Stuff
  #
  # public_dns_name is unicode format
  fqdn = str(instance.public_dns_name)
  login = ssh_user + '@' + fqdn 

  # FIXME
  # if all attempts failed we have an instance that's not used
  # and an extra volume attached to it that's not used
  # maybe we should clean up.

  # the very first time we will try 5 times to connect instance and give time to properly boot
  for i in range(5):
    # exec_remote returns True or False
    if exec_remote(login, 'uname -a'):
      break
    else:
      time.sleep(10)
  
  #
  # Prepare mount point for rsync
  # 
  # mkfs.ext4 /dev/xvdh
  # sudo mkdir /backup
  # sudo mount /dev/xvdh /backup
  #'hanning(%d).pdf' % num 
  exec_remote(login, '[ -b %s] && echo success' % device)
  exec_remote(login, 'sudo mkfs.ext4 %s' % device )
  exec_remote(login, 'sudo mkdir %s' % mountpoint)
  exec_remote(login, 'sudo mount %s %s' %(device,mountpoint))
  exec_remote(login, 'mount')
  exec_remote(login, 'df -h %s' % mountpoint)

  #
  # finally terminate the instance
  #
  #print 'Cleanup time ID terminating: ', instance.id
  #time.sleep(10)
  #connection.terminate_instances(instance_ids=[instance.id])
 
  sys.exit(0)

def print_env():
  # FIXME
  if 'EC2_BACKUP_VERBOSE' in os.environ:
    print os.environ['EC2_BACKUP_VERBOSE']
  if 'AWS_CONFIG_FILE' in os.environ:
    print os.environ['AWS_CONFIG_FILE']
  if 'EC2_CERT' in os.environ:
    print os.environ['EC2_CERT']
  if 'EC2_HOME' in os.environ:
    print os.environ['EC2_HOME']
  if 'EC2_PRIVATE_KEY' in os.environ:
    print os.environ['EC2_PRIVATE_KEY']




#
# run Main
#
if __name__ == "__main__":
  Main()
