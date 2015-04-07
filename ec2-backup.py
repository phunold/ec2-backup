#!/usr/bin/env python

import os
import subprocess
import sys
import boto.ec2

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
ec2 = boto.ec2.connect_to_region("us-east-1")
print ec2
# FIXME should use 'ec2.get_all_reservations' but this boto version seems does not have it
reservations = ec2.get_all_instances()
for reservation in reservations:
  for instance in reservation.instances:
    instance_name = instance.tags['Name']
    instance_id = instance.id
    ip = instance.ip_address
    state = instance.state
    ami = instance.image_id
#    print instance.__dict__.keys()
    print "Name:", instance_name, "ID:", instance_id, "IP:", ip, "State:", state, "AMI:", ami

sys.exit()

HOST="54.160.192.98" # test EC2 instance Fedora 20 ami-3b361952
COMMAND="sudo id"

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

