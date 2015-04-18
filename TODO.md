* P DONE: command line options ec2-backup [-h] [-m method] [-v volume-id] dir
* G DONE: calculate size of local directory (size X)
* G DONE: Create new EBS devices of size X
* P DONE: Create/start/terminate EC2 instance (including EC2_BACKUP_FLAGS_AWS)
* G DONE: Attach EBS to instance
* G: Method 1: DD utilizing tar(1) on the local host and dd(1) on the remote instance
* P DONE: Method 2: Rsync to EBS (including EC2_BACKUP_FLAGS_SSH)
* P: Debug switch for verbose messages EC2_BACKUP_VERBOSE
* P: Figure out the ssh-key to use for creating instance/ssh/rsync/dd
