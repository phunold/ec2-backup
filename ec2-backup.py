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
# please don't change unless you know what you're doing
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

  # get additional ssh options from environment and append to comamnd_list
  if 'EC2_BACKUP_FLAGS_SSH' in os.environ:
    command_list.extend(os.environ['EC2_BACKUP_FLAGS_SSH'].split())

  # add login user@target and the remote command to execute
  command_list.append(login) # single string
  command_list.extend(remote_command.split()) # multiple strings potentially

  return execute(command_list)

def execute(commands):
  print "cmd:", " ".join(commands)
  # Popen expects a list of arguments
  #proc = subprocess.Popen(commands, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  try:
    result = subprocess.check_output(commands, stderr=subprocess.STDOUT)
  except subprocess.CalledProcessError, e:
    # Test result
    print "cmd:", e.cmd
    print "cmd:", ' '.join(e.cmd)
    print "rc:", e.returncode
    print "output", e.output
    return False

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
    sys.exit(1)
  
  # connect_to_region return None if region is unkown or incorrect
  if not connection:
    print 'Wrong or unknown region:', region
    sys.exit(1)

  return connection
  
def create_ec2_instance(connection,ami):
  # FIXME key needs to be default or from ENV
  try:
    reservations = connection.run_instances(ami,key_name='pstam-keypair')
  except boto.exception.EC2ResponseError, e:
    print "Error running new instance:", e
    sys.exit(1)
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
  # Connect to EC2 Region
  #
  connection = connect_ec2(region)

  # 
  # Prepare EBS Volume
  #  
  # create or retrieve EBS volume
  if options.volumeid:
    # FIXME check if volume actually exists
    volume = connection.get_all_volumes([options.volumeid])[0]
  else:
    volume = connection.create_volume(size, zone)
    print 'Creating volume (size/zone): (%s/%s)' % (size, zone)

    # wait until volume is ready
    status = volume.update()
    while status == 'creating':
      print 'Waiting for volume to be ready:', status
      time.sleep(5)
      status = volume.update()

  # update a name for convenience
  volume.add_tag("Name","ec2-backup")

  #
  # run new EC2 instance 
  # 
  instance = create_ec2_instance(connection, ami)
  # convert to string since public_dns_name is unicode format
  fqdn  = str(instance.public_dns_name)
  login = ssh_user + '@' + fqdn 

  # 
  # attach volume to new instance
  # 
  # ebs_device looks like this '/dev/sdh' but will become /dev/xvdh on EC2 HVM
  try:
    connection.attach_volume(volume.id, instance.id, ebs_device)
  except boto.exception.EC2ResponseError, e:
    print 'Failed to attach volume:', volume.id
    print e
    sys.exit(1)

  # FIXME
  # if all attempts failed we have an instance that's not used
  # and an extra volume attached to it that's not used
  # maybe we should clean up.

  # try 5 times to connect instance and give time to boot up
  for i in range(5):
    # exec_remote returns True or False
    if exec_remote(login, 'uname'):
      break
    else:
      time.sleep(10)
  else:
    print "ERROR could not connect host:", login  
    sys.exit(1)

  #
  # backup with dd or rsync
  #
  if (options.method == 'dd'):
    print 'dd not implemented'
    # tar -cvf - {1} | ssh key \'dd of={2}\' (login, backupdir, str(attach)
  else:
    #
    # Prepare mount point for rsync
    # 
    # FIXME
    # check commands executed sucessfully
    # 
    # check if block device exists
    exec_remote(login, '[ -b %s ] && echo success' % device)
    # create ext4 filesystem (other fstypes may feasible)
    exec_remote(login, 'sudo mkfs.ext4 %s && echo success' % device )
    # create directory for mountpoint
    exec_remote(login, 'sudo mkdir %s && echo success' % mountpoint)
    # FIXME
    # rsync cannot change timestamps need additional mount flags set (atime?)
    exec_remote(login, 'sudo mount %s %s && echo success' %(device,mountpoint))
    # chown to default ssh_user (ubuntu) for permission
    exec_remote(login, 'sudo chown -R %s:%s /backup && echo success' % (ssh_user,ssh_user))

    #
    # rsync
    #
    ssh_opts = ''
    # FIXME this is redundant to exec_remote
    # get additional ssh options from environment
    if 'EC2_BACKUP_FLAGS_SSH' in os.environ:
      ssh_opts = os.environ['EC2_BACKUP_FLAGS_SSH']
    
    # execute function expects a "list" of commands
    rsync_cmd = ['rsync','-avz', '--delete', '-e']
    rsync_cmd.append('ssh %s' % ssh_opts)
    rsync_cmd.extend(('%s %s:%s' % (backupdir,login,mountpoint)).split())

    execute(rsync_cmd)
    
  #
  # finally terminate the instance
  #
  #print 'Cleanup time ID terminating: ', instance.id
  #time.sleep(10)
  #connection.terminate_instances(instance_ids=[instance.id])
 
  print volume.id
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
