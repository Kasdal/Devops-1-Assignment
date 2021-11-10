#Imports
import boto3, os, webbrowser, time, subprocess, uuid
from operator import itemgetter
from datetime import datetime, timedelta

########################################################################################################
########################################################################################################
# variables and user content that will install lamp server after the instance is initialized.
aws_region = "eu-west-1"
user_data_content = """#!/bin/bash
sudo yum update -y
sudo amazon-linux-extras install -y lamp-mariadb10.2-php7.2 php7.2
sudo yum install -y httpd mariadb-server
sudo systemctl start httpd
sudo systemctl is-enabled httpd
echo '<html>' > index.html
echo 'Private IP address: ' >> index.html
curl http://169.254.169.254/latest/meta-data/local-ipv4 >> index.html
echo '\n Mac address : ' >> index.html
MAC_ADDRESS=$(curl http://169.254.169.254/latest/meta-data/mac)
curl http://169.254.169.254/latest/meta-data/mac >> index.html
echo '\n Subnet id : ' >> index.html
curl http://169.254.169.254/latest/meta-data/network/interfaces/macs/"$MAC_ADDRESS"/subnet-id >> index.html
cp index.html /var/www/html/index.html"""
 
# initialize boto3 ec2, S3, CW, sns client and resource variables
ec2_resource = boto3.resource('ec2', aws_region)
ec2_client = boto3.client('ec2', aws_region)

s3 = boto3.resource("s3")  
s3_client = boto3.client('s3')
cloudwatch = boto3.resource('cloudwatch')
sns = boto3.client("sns", aws_region)

#Create SNS topic and subscription

response = sns.create_topic(Name="RunningInstanceAlert")
topic_arn = response["TopicArn"]

response = sns.list_topics()
topics = response["Topics"]

#Note that in order to test this, valid email is needed and subscription confirmed
response = sns.subscribe(TopicArn=topic_arn, Protocol="EMAIL", Endpoint="email@hotmail.com") #edit email address for subscription
subscription_arn = response["SubscriptionArn"]

########################################################################################################
########################################################################################################
#Unique S3 bucket name
bucketName = 'plesmilan' + '-' + uuid.uuid4().hex
print(bucketName)
# Error handling
errorLog = open('err.txt', 'w')
now = datetime.now()
os_time = now.strftime("%H:%M:%S")

########################################################################################################
########################################################################################################
#S3 bucket creation and website creation
try:
    new_bucket = s3.create_bucket(
        Bucket=bucketName,
        ACL='public-read',
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )
    subprocess.run("curl -O http://devops.witdemo.net/assign1.jpg", shell=True)
    s3.Object(bucketName, 'assign1.jpg').put(Body=open('assign1.jpg',
                                                         'rb'), ACL='public-read')
    URL = "https://%s.s3.%s.amazonaws.com/%s" % (
        bucketName, "eu-west-1", "assign1.jpg")
    subprocess.run(
        "echo ' <html>  \n <img src=%s alt=\"assign1.jpg\"> \n </html>' > index.html" % (URL), shell=True)
    s3.Object(bucketName, 'index.html').put(Body=open('index.html',
                                                        'rb'), ACL='public-read', ContentType='text/html')
    website_configuration = {
        'IndexDocument': {'Suffix': 'index.html'},
    }
    s3_client.put_bucket_website(
        Bucket=bucketName, WebsiteConfiguration=website_configuration)
    new_bucket.wait_until_exists()
    print('Bucket Created Successfully')
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))

try:
    webbrowser.open_new_tab(
        'http://' + bucketName + '.s3-website-eu-west-1.amazonaws.com')
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))

########################################################################################################
########################################################################################################
#Security group creation
try:
    securitygroup = ec2_resource.create_security_group(GroupName='SSH-HTTP', Description='ssh and http ingress', VpcId='vpc-2fc12556')
    securitygroup.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=22, ToPort=22)
    securitygroup.authorize_ingress(CidrIp='0.0.0.0/0', IpProtocol='tcp', FromPort=80, ToPort=80)
    print('Security Group with ID ' + securitygroup.id + ' created successfully')
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
########################################################################################################
########################################################################################################
#Creating new SSH key and changing its permissions to 600
try:
    outfile = open('Secretkey.pem','w')
    keypair = ec2_client.create_key_pair(KeyName='Secretkey')
    keyval = keypair['KeyMaterial']
    outfile.write(keyval)
    outfile.close()
    subprocess.run("chmod 400 Secretkey.pem", shell=True)
    print('Key created')
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))

########################################################################################################
########################################################################################################
# get the latest AMI ID for Amazon Linux 2
try:
    ec2_ami_ids = ec2_client.describe_images(
        Filters=[{'Name':'name','Values':['amzn2-ami-hvm-2.0.????????-x86_64-gp2']},{'Name':'state','Values':['available']}],
        Owners=['amazon']
    )
    image_details = sorted(ec2_ami_ids['Images'],key=itemgetter('CreationDate'),reverse=True)
    ec2_ami_id = image_details[0]['ImageId']
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
########################################################################################################
########################################################################################################
#Creating the insance with the following specs.
try:
    ec2_instance = ec2_resource.create_instances(
    ImageId=ec2_ami_id,
    InstanceType='t2.nano',
    KeyName='Secretkey',
    MaxCount=1,
    MinCount=1,
    UserData=user_data_content,
    TagSpecifications = [
        {
            "ResourceType": "instance",
            "Tags": [
                {
                    "Key": "Name",
                    "Value": "Webserver"
                }
            ]
        }
    ],
    #Associate network and SG with the instance.
    NetworkInterfaces=[{
    'SubnetId': 'subnet-0194416258010c48d',
    'DeviceIndex': 0,
    'AssociatePublicIpAddress': True,
    'Groups': [securitygroup.group_id]
    }],
    )
    #Grab instance ID and store it.
    ec2_instance_id = ec2_instance[0].id
    print('Creating EC2 instance')
    
    #wait untill the ec2 is running then return instance ID
    waiter = ec2_client.get_waiter('instance_running')
    waiter.wait(InstanceIds=[ec2_instance_id])
    print('EC2 Instance created successfully with ID: ' + ec2_instance_id)

    # print webserver ip address
    ec2_instance = ec2_client.describe_instances(
        Filters=[{'Name': 'tag:Name','Values': ['Webserver']},
        {'Name': 'instance-state-name','Values': ['running']}]
    )
    ec2_public_ip_address = ec2_instance["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    print('Webserver URL: ' + ec2_public_ip_address)
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
########################################################################################################
########################################################################################################
# Need a script to sleep for the instance to be fully initialized, could use waiter to wait for status sheck to be 2/2 also.
time.sleep(180)

webbrowser.open_new_tab("http://" + ec2_public_ip_address) 

print ("Web server running")

#Alerts the user by email address that the instance is ready.
sns.publish(TopicArn=topic_arn, 
            Message="Instance with ip: " + ec2_public_ip_address + " is running", 
            Subject="Instance alert")
try:
    print('********  Uploading monitoring  **********')
    subprocess.run("scp -o StrictHostKeyChecking=no -i Secretkey.pem monitor.sh ec2-user@" + ec2_public_ip_address + ":~", shell=True)
    print('********  Accessing permissions  **********')
    subprocess.run("ssh -o StrictHostKeyChecking=no -i Secretkey.pem ec2-user@" + ec2_public_ip_address + " 'chmod +x ~/monitor.sh'", shell=True)
    print('********  Running script now  **********')
    subprocess.run("ssh -o StrictHostKeyChecking=no -i Secretkey.pem ec2-user@" + ec2_public_ip_address + " ./monitor.sh", shell=True)
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))    
########################################################################################################
########################################################################################################
print("You will now wait 6 minutes for Cloudwatch to gather some data about the instance.")

#Monitoring
try:
    instance = ec2_resource.Instance(ec2_instance_id)
    instance.monitor()  # Enables detailed monitoring on instance (1-minute intervals)
    time.sleep(360)     # Wait 6 minutes to ensure we have some data (can remove if not a new instance)

    metric_iterator = cloudwatch.metrics.filter(Namespace='AWS/EC2',
                                                MetricName='CPUUtilization',
                                                Dimensions=[{'Name':'InstanceId', 'Value': ec2_instance_id}])

    metric = list(metric_iterator)[0]    # extract first (only) element

    response = metric.get_statistics(StartTime = datetime.utcnow() - timedelta(minutes=5),   # 5 minutes ago
                                    EndTime=datetime.utcnow(),                              # now
                                    Period=300,                                             # 5 min intervals
                                    Statistics=['Average'])

    # total disk read
    disk_read_iterator = cloudwatch.metrics.filter(Namespace='AWS/EC2',
                                    MetricName='DiskReadBytes',
                                    Dimensions=[{'Name': 'InstanceId', 'Value': ec2_instance_id}])                                            
    disk_read_metric = list(disk_read_iterator)[0]
    disk_read_response = disk_read_metric.get_statistics(StartTime=datetime.utcnow() - timedelta(minutes=5),   # 5 minutes >
                                    EndTime=datetime.utcnow(),                              # now
                                    Period=300,                                             # 5 min intervals
                                    Statistics=['Sum'])

    # total network out
    net_iterator = cloudwatch.metrics.filter(Namespace='AWS/EC2',
                                    MetricName='NetworkOut',
                                    Dimensions=[{'Name': 'InstanceId', 'Value': ec2_instance_id}])
    net_metric = list(net_iterator)[0]
    net_response = net_metric.get_statistics(StartTime=datetime.utcnow() - timedelta(minutes=5),   # 5 mi>
                                                        EndTime=datetime.utcnow(),                              # now
                                                        Period=300,                                             # 5 min intervals
                                                        Statistics=['Sum'])

    print ("Average CPU utilisation:", response['Datapoints'][0]['Average'], response['Datapoints'][0]['Unit'])
    print ("Average DiskReadBytes", disk_read_response['Datapoints'][0]['Sum'], response['Datapoints'][0]['Unit'])
    print ("Agregated network out", net_response['Datapoints'][0]['Sum'], response['Datapoints'][0]['Unit'])
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
########################################################################################################
########################################################################################################
####Sleep for few minutes min to talk about the script and delete the bucket and objects and the rest of the infrastructure####

time.sleep(1)

try:
    bucket = boto3.resource('s3').Bucket(bucketName)
    bucket.objects.all().delete()
    bucket.delete()
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
else:
    print("Bucket was succesfully cleaned")

########################################################################################################
########################################################################################################
#Clean the infrastructure after examination  ###########################################################
########################################################################################################
########################################################################################################
try:
    myvpc = ec2_client.describe_vpcs(
        Filters=[{'Name': 'tag:Name','Values': ['default-vpc']}]
    )
    vpc_id = myvpc["Vpcs"][0]["VpcId"]
    
    vpc = ec2_resource.Vpc(vpc_id)
    
    # delete ec2 instance
    ec2_instance = ec2_client.describe_instances(
        Filters=[{'Name': 'tag:Name','Values': ['Webserver']}
        ,{'Name': 'instance-state-name','Values': ['running']}]
    )
    ec2_instance_id = ec2_instance["Reservations"][0]["Instances"][0]["InstanceId"]
    ec2_client.terminate_instances(InstanceIds=[ec2_instance_id])
    print('Terminating EC2 instance')
    
    #wait untill the ec2 is terminated
    waiter = ec2_client.get_waiter('instance_terminated')
    waiter.wait(InstanceIds=[ec2_instance_id])
    print('EC2 instance with ID ' + ec2_instance_id + ' deleted successfully')

    # delete key pair
    ec2_client.delete_key_pair(KeyName='Secretkey')
    os.remove("Secretkey.pem")
    print('Key Pair Secretkey deleted successfully')
except Exception as error:
    print(error)
    errorLog.write("\n" + os_time + "- " + str(error))
else:
    print("Infrastructure is destroyed") 

