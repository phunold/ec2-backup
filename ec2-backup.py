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
region = 'us-east-1'
# Ubuntu 12.04 LTS AMD64 EBS
# http://cloud-images.ubuntu.com/locator/ec2/ 
ami = 'ami-00615068'
ssh_user = 'ubuntu'

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

  return connection

def create_ec2_instance(connection,ami):
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
  # [:-1] returns everything but the last character 
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
  print 'Estimate Directory size in GB: %s' % estimate_size(backupdir)

  #
  # run new EC2 instance 
  # 
  connection = connect_ec2(region)

  server_instance = create_ec2_instance(connection, ami)

  fqdn = server_instance.public_dns_name
  print 'server hostname: ', fqdn

  #
  # SSH/TAR/Stuff
  #

  #
  # finally terminate the instance
  #
  print 'Cleanup time ID terminating: ', server_instance.id
  time.sleep(10)
  connection.terminate_instances(instance_ids=[server_instance.id])
 
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




def myssh():
  HOST="54.160.192.98" # test EC2 instance Fedora 20 ami-3b361952
  COMMAND="sudo id"
  #
  ssh = subprocess.Popen(["ssh", "-t", "-i", os.environ['EC2_PRIVATE_KEY'], "fedora@%s" % HOST, COMMAND],
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
  result = ssh.stdout.readlines()
  if result == []:
     error = ssh.stderr.readlines()
     print >>sys.stderr, "ERROR: %s" % error
  else:
     print result

#
# run Main
#
if __name__ == "__main__":
  Main()
