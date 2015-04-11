#!/usr/bin/env python

import os
import subprocess
from subprocess import PIPE
import sys
# FIXME catch ImportError: No module named boto.ec2
import boto.ec2
import optparse

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

  #print "size in GB (rounded up):", estimate_size(sys.argv[1])
  #sys.exit(1)
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


def myec2():
  # Connect to EC2
  # print boto.config.__dict__
  # check if credentials setup
  # boto.exception.NoAuthHandlerFound: No handler was ready to authenticate. 1 handlers were checked. ['QuerySignatureV2AuthHandler'] Check your credentials
  try:
    ec2 = boto.ec2.connect_to_region("us-east-1")
  except boto.exception.NoAuthHandlerFound:
    print "Could not authenticate to ec2!"
    print "run 'aws configure' or setup EC2 keys"
    sys.exit(1)

  # FIXME should use 'ec2.get_all_reservations' but this boto version seems does not have it
  reservations = ec2.get_all_instances()
  for reservation in reservations:
    for instance in reservation.instances:
      instance_name = instance.tags['Name']
      instance_id = instance.id
      ip = instance.ip_address
      state = instance.state
      ami = instance.image_id
  #   print instance.__dict__.keys()
      print "Name:", instance_name, "ID:", instance_id, "IP:", ip, "State:", state, "AMI:", ami



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
