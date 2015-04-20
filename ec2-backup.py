#!/usr/bin/env python

# author: Philipp Hunold <phunold@stevens.edu>
# author: Georgios Kapoglis <gkapogli@stevens.edu>

import os
import sys
import optparse
import subprocess
from subprocess import PIPE
import time # for sleep
import boto.ec2

#
# global settings
# 
# Prefered Region and zone
# taken from volume if provided
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

def info(msg):
  if 'EC2_BACKUP_VERBOSE' in os.environ:
    now = time.strftime("%c")
    print 'INFO %s: %s' % (now, msg)

def fatal(msg):
  now = time.strftime("%c")
  print 'FATAL %s: %s' % (now, msg)
  sys.exit(1)

def exec_remote(login, ssh_opts, remote_command):
  # login contains 'ssh_user@ec2.host.amazon.com'
  # -t simulates terminal required for sudo
  # FIXME
  # StrictHostKeyChecking maybe delegate to user 
  # and make it part of EC2_BACKUP_FLAGS_SSH
  ssh_cmd= 'ssh -t -o StrictHostKeyChecking=no %s %s %s' % (ssh_opts,login,remote_command)
  return execute(ssh_cmd)

def execute(cmd):
  info(cmd)
  proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  stdout, stderr = proc.communicate()
  rc = proc.returncode
  if rc == 0:
    return True
  else:
    return False

def connect_ec2(region):
  # Connect to EC2
  # print boto.config.__dict__
  # check if credentials setup
  # boto.exception.NoAuthHandlerFound: No handler was ready to authenticate. 1 handlers were checked. ['QuerySignatureV2AuthHandler'] Check your credentials
  try:
    connection = boto.ec2.connect_to_region(region)
  except boto.exception.NoAuthHandlerFound:
    fatal("Could not authenticate to ec2!")
  
  # connect_to_region return None if region is unkown or incorrect
  if not connection:
    fatal('Wrong or unknown region: %s' % region)

  return connection
  
def parse_aws_opts(flags):
  # since we are using boto the parameter options are passed a bit different than on the aws cli tool
  # example: aws ec2 run-instances --image-id ami-bc8131d4 --key-name ssh-aws-keypair
  # reference default value from boto ec2:
  # http://boto.readthedocs.org/en/latest/ref/ec2.html#boto.ec2.connection.EC2Connection.run_instances
  opts = {'key_name': None, 'instance_type': 'm1.small', 'security_groups': None}
  for flag in flags.strip().split('--')[1:]:
    key,value = flag.split()
    # all parameters in ec2.boto are with underscore instead of dash
    opts[key.replace('-','_')] = value
  return opts

def create_ec2_instance(connection,ami,placement,flags):
  # we need to parse the options
  # see 'parse_aws_opts' for more info
  aws_opts = parse_aws_opts(flags)
  try:
    reservations = connection.run_instances(ami, placement=placement, key_name=aws_opts['key_name'], instance_type=aws_opts['instance_type'], security_groups=aws_opts['security_groups'])
  except boto.exception.EC2ResponseError, e:
    fatal("Error running new instance: %s" % e)

  # get instance and wait until ready
  instance = reservations.instances[0] 
  status = instance.update()
  while status == 'pending':
    info('Waiting for instance to be ready: %s' % status)
    time.sleep(5)
    status = instance.update()
  
  # add EC2 for convenience
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
   
  # 
  # additional validation on the directory 
  # 
  backupdir = args[0]

  if not os.path.exists(backupdir):
    parser.error('directory does not exist: %s' % backupdir)

  if not os.path.isdir(backupdir):
    parser.error('not a directory: %s' % backupdir )

  # print if DEBUG
  info('Backup method    : %s' % options.method)
  info('Backup volumeid  : %s' % options.volumeid)
  info('Backup directory : %s' % backupdir)

  #
  # check environment variables
  # 
  ssh_opts = ''
  if 'EC2_BACKUP_FLAGS_SSH' in os.environ:
    ssh_opts = os.environ['EC2_BACKUP_FLAGS_SSH']
  info('Backup SSH flags: %s' % ssh_opts)
  
  aws_opts = ''
  if 'EC2_BACKUP_FLAGS_AWS' in os.environ:
    aws_opts = os.environ['EC2_BACKUP_FLAGS_AWS']
  info('Backup AWS flags: %s' % aws_opts)

  # 
  # calculate size of directory in GB
  # 
  size = estimate_size(backupdir)
  info('Local directory size in GB: %s' % size)

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
    info('Retrieving existing volume: %s' % options.volumeid)
    volume = connection.get_all_volumes([options.volumeid])[0]
    # set zone from this volume to make sure we can attach to instance
  else:
    volume = connection.create_volume(size, zone)
    info('Creating volume of size in zone: %s %s' % (size,zone))

    # wait until volume is ready
    status = volume.update()
    while status == 'creating':
      info('Waiting for volume to be ready: %s' % status)
      time.sleep(2)
      status = volume.update()

  # update a name for convenience
  volume.add_tag("Name","ec2-backup")

  #
  # run new EC2 instance in zone from volume
  # 
  instance = create_ec2_instance(connection, ami, volume.zone, aws_opts)
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
    fatal('Failed to attach volume: %s %s' % (volume.id, e))

  # FIXME
  # if all attempts to connect fail we have an instance that's not used
  # and an extra volume attached to it that's not used

  # try 5 times to connect instance and give time to boot up
  for i in range(9):
    if exec_remote(login, ssh_opts, 'uname'):
      break
    else:
      time.sleep(12)
  else:
    fatal("Could not connect to host: %s %s" % (login,ssh_opts))

  #
  # backup with dd or rsync
  #
  
  if (options.method == 'dd'):
    execute('tar -cvf - %s | ssh %s %s \"sudo dd of=%s\"' % (backupdir,ssh_opts,login,device))

  else:
    #
    # Prepare mount point for rsync
    # 
    # FIXME
    # check commands executed sucessfully
    # 
    # check if block device exists
    exec_remote(login, ssh_opts, '[ -b %s ] && echo success' % device)
    # create ext4 filesystem (other fstypes may feasible)
    exec_remote(login, ssh_opts, 'sudo mkfs.ext4 %s && echo success' % device )
    # create directory for mountpoint
    exec_remote(login, ssh_opts, 'sudo mkdir %s && echo success' % mountpoint)
    # FIXME
    # rsync cannot change timestamps need additional mount flags set (atime?)
    exec_remote(login, ssh_opts, 'sudo mount %s %s && echo success' %(device,mountpoint))
    # chown to default ssh_user (ubuntu) for permission
    exec_remote(login, ssh_opts, 'sudo chown -R %s:%s /backup && echo success' % (ssh_user,ssh_user))

    #
    # rsync
    #
    # FIXME we create a mirror and not backup with --delete maybe remove it?
    rsync_cmd = 'rsync -avz --delete -e \"ssh %s\" %s %s:%s' % (ssh_opts,backupdir,login,mountpoint)

    execute(rsync_cmd)
    
  #
  # finally terminate the instance
  #
  info('Cleanup time terminating instance: %s' % instance.id)
  time.sleep(10)
  connection.terminate_instances(instance_ids=[instance.id])
 
  # output volume identifier in any case
  print volume.id
  sys.exit(0)

#
# run Main
#
if __name__ == "__main__":
  Main()

