HOW TO LOAD THE STEDT DATABASE DUMP INTO YOUR OWN SQL SERVER

v1.0 11 June 2017

A dump of the MySQL database supporting the STEDT project in included in this folder.

This readme covers the very basics about how to take that backup and restore it to your
own MySQL server.

To learn how to install one of the several interfaces that can access this database, see:

   https://github.com/stedt-project/sss

in particular:

   https://github.com/stedt-project/sss/tree/master/archiving/dump
   
The steps are quite simple, but there are a couple places where you can go into the weeds; systems differ and
not all eventualties can be anticipated.

The steps are (not necessarily all in strict order; you may already have some of requirements)

* Install MySQL (not covered here).
* Create an empty database with appropriate permissions (see below).
* Obtain the compressed backup.
* Decompress it.
* Restore it.

Not described here is how to install a MySQL server on your system. Having installed MySQL, you  need to do
something like the following to create the empty database (NB: these are suggestions, details may vary):

# login as root, presuming your database server was installed with a superuser "root";
# of course u know the password
$ mysql -u root -p
# create the stedt database and give a user access to it:
mysql> CREATE DATABASE stedt;
mysql> GRANT ALL PRIVILEGES ON stedt.* TO 'stedtadmin'@'localhost' IDENTIFIED BY 'password';
mysql> QUIT
# after this, you can access your copy of the stedt db as follows:
$ mysql -D stedt -u stedtadmin -p


You should now have:

* A database named 'stedt'
* A user with permissions to write to that database

Obtain the compressed dump from the archive (TBD!)

$ bunzip2 STEDT_public_20160602.sql.bz2 
$ mysql -D stedt < STEDT_public_20160602.sql

NB: if you see:

ERROR 1045 (28000): Access denied for user 'xxxx'@'localhost' (using password: YES)

you can try something like:

$ mysql -u myauthorizeduser -p -D stedt < STEDT_public_20160602.sql

(this will take a few minutes)

$ mysql -D stedt -u myauthorizeduser -p --default-character-set=utf8
