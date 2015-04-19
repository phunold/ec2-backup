# README EC2-BACKUP

## Information

We chose *boto.ec2* module for for this program for multiple reasons:
* learning (python) by doing
* python boto.ec2 module for ease of use with EC2 communications
* python subprocess allows for flexible interactions with shell commands

A few aspects why a shell script might have been the better choice:
* pythons subprocessing was not always intuitive in the beginning at least about what characters it escapes, what quotes is drops silently and what is actually interpreted as command line argument.
* the format of *EC2_BACKUP_FLAGS_AWS* are for *aws* tool, which is slightly different to how boto.ec2 is calling the arguments. We developed a function to map the names. Since it's a 1 to 1 mapping only following options are available:
  * key_name
  * instance_type
  * security_groups

When running multiple instances and volumes it can be difficult to keep track of instance-id and volume-id. We decide to add a name *Tag* to the instance and the volume for convenience.
* instance.add_tag('Name', 'EC2-Backup Helper Instance')
* volume.add_tag("Name","ec2-backup")

## Global Settings
### Region + Availability Zone
The program uses predefined choices for Region and Availability Zones, which can be changed to the users like. We launch the instance in that Region/Zone unless there is a provided Volume-ID then we launch the instance in the exact same Region/Zone that Volume exists.

### Devices and logical disks
The device allocated on volume creation is */dev/sdh* which becomes */dev/xvdh* in EC2's HVM environment.


