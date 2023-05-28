import json
import boto3
import os
import datetime
from botocore.exceptions import ClientError
from datetime import date, timedelta

################### Send SNS Notification ##############################
class send_sns_notification:
    def __init__(self, sns_arn, message, subject):
        self.sns_arn = sns_arn
        self.message = message
        self.subject = subject
        self.sns     = boto3.client('sns')

    def sns_publish(self):
        response = self.sns.publish(
            TopicArn = self.sns_arn,
            Message  = self.message,
            Subject  = self.subject
        )

        return {
            'statuscode' : 200,
            'body'       : response
        }

############# This code is exceuted every 25 days to rotate keys #########################
class access_key_creation:
    def __init__(self, userdetails,secret,event_name, sns_arn, tags, flag, lambda_arn, rotation_day):
        self.secret         = secret
        self.userdetails    = userdetails
        self.sns_arn        = sns_arn
        self.event_name     = event_name
        self.tags           = tags
        self.flag           = flag
        self.lambda_arn     = lambda_arn
        self.rotation_day   = rotation_day
        self.iam            = boto3.client('iam')
        self.event          = boto3.client('events')
        self.secretsmanager = boto3.client('secretsmanager')

    def create_new_access_key(self):
        try:
            for username in self.userdetails:
                user = username['UserName']
                secretname = self.secret
                if username['key_count'] <= 1:
                    create_response    = self.iam.create_access_key(UserName= user)
                    new_acceskey       = create_response['AccessKey']['AccessKeyId']
                    print("A new set of keys has been created for user - " + user)
                    new_secret      = '{"UserName":"' + create_response['AccessKey']['UserName'] + '", "AccessKeyId":"' + create_response['AccessKey']['AccessKeyId'] + '", "SecretAccessKey":"' + create_response['AccessKey']['SecretAccessKey'] + '"}'
                    try:
                        # Get previous secret version.
                        previous_version = self.secretsmanager.get_secret_value(SecretId= secretname)
                        previous_version = previous_version['VersionId']
                        # Updating the secret value
                        updated_secret = self.secretsmanager.update_secret(SecretId= self.secret,SecretString= new_secret)
                        updated_version = updated_secret['VersionId']
                        print(secretname + " secret has been updated with latest key details for " + user + " user.")
                    
                    except ClientError as e:
                        if e.response['Error']['Code'] == 'ResourceNotFoundException':
                            # We can't find the resource that you asked for.
                            # Deal with the exception here, and/or rethrow at your discretion.
                            request = self.secretsmanager.create_secret(
                                Name              = secretname, 
                                Description       = 'Auto-created secret',
                                SecretString      = new_secret,
                                RotationLambdaARN = self.lambda_arn,
                                RotationRules     = {
                                    'AutomaticallyAfterDays': self.rotation_day
                                },
                                Tags              = self.tags   
                            )
                            previous_version = "null"
                            updated_version  = request['VersionId']

                        else :
                            raise e

                    ######################send sns notification ######################################
                    if self.flag == 1:
                        message = f'''
                        Hi Team,

                        New IAM Access Key has been Created and credentials are stored in SecretsManager.
                        Older IAM Access Key will be deactivated and deleted after 10 days from now.
                        During this 10 days please fetch new access keys from secretsmanager, update and check that new credentials are fine.
                        
                        IAM User                : {user}
                        Latest AccessKey        : {new_acceskey}
                        Expire Date             : {(date.today()+timedelta(days=35)).isoformat()}
                        SecretManager           : {secretname}
                        Current Secret Version  : {updated_version}
                        Previous Secret Version : {previous_version}
                        
                        Thanks & regards
                        Govindaraju N
                        '''
                    else:
                        self.event.put_rule(
                            Name=self.event_name,
                            ScheduleExpression= "rate(24 hours)"
                        )
                        message = f'''
                        Hi Team,

                        New IAM Access Key has been Created and credentials are stored in SecretsManager.
                        IAM User                : {user}
                        Latest AccessKey        : {new_acceskey}
                        Expire Date             : {(date.today()+timedelta(days=35)).isoformat()}
                        SecretManager           : {secretname}
                        Current Secret Version  : {updated_version}
                        Previous Secret Version : {previous_version}
                        
                        Thanks & regards
                        Govindaraju N
                        '''
                    subject = f"[Important] IAM update for user: {user}."
                    send_email = send_sns_notification(self.sns_arn, message, subject)
                    send_email.sns_publish()
            
        except Exception as e:
            print(e)

        return "Process key creation & secret update has completed successfully."
######################## Code to cleanup old key ###############################################################       
class iam_credentials_cleanup:
    def __init__(self, secret, userdetails, sns_arn):
        self.secret         = secret
        self.userdetails    = userdetails
        self.sns_arn        = sns_arn
        self.iam            = boto3.client('iam')
        self.secretsmanager = boto3.client('secretsmanager')

    def old_keys_cleanup(self):
        try:
            for iam in self.userdetails:
                username = iam['UserName']
                # Get oldest key.
                oldest_key = iam['AccessKeyId']

                # deactivate the oldest key.
                self.iam.update_access_key(AccessKeyId=oldest_key, Status='Inactive',UserName= username)
                
                # deleting the oldest access key.
                self.iam.delete_access_key(AccessKeyId=oldest_key, UserName= username)
                
                print("IAM access key - " + oldest_key + ", of " + username + " user has been inactivated and deleted.")
                ######################send sns notification ######################################
                message = f'''
                Hi Team,

                Older IAM Access Key {oldest_key} has been deleted as informed in the previous email.
                
                IAM User                   : {username}
                Deleted IAM Access Key Age : {iam['key_age']}
                Deleted IAM Access Key     : {oldest_key}
                
                Thanks & regards
                Govindaraju N
                '''
                subject = f"[Important] Older IAM Access Key Deleted for user: {username}."
                send_email = send_sns_notification(self.sns_arn, message, subject)
                send_email.sns_publish()
        except Exception as e:
            print(e)
        return "Process of inactive key deletion completed successfully."

############### List the access keys for the given IAM User #####################################
class list_access_keys:
    def __init__(self, username):
        self.username = username

    def list_keys(self):
        try:
            username    = self.username
            iam         = boto3.client('iam')
            accesskeys  = iam.list_access_keys(UserName=username)
            count       = len(accesskeys['AccessKeyMetadata'])
            key_details = []
            if count >= 1:
                for key in accesskeys['AccessKeyMetadata']:
                    key_age = self.time_diff(key['CreateDate'])
                    response = iam.get_access_key_last_used(AccessKeyId= key['AccessKeyId'])
                    if 'LastUsedDate' in response['AccessKeyLastUsed']:
                        last_used = response['AccessKeyLastUsed']['LastUsedDate']
                        non_active_days = self.time_diff(last_used)
                        if non_active_days == 0: non_active_days = 'today'
                        else: non_active_days = f"{self.time_diff(last_used)} Days"
                    else:
                        non_active_days = "never"
                    key_notify   = {}
                    key_notify['UserName']    =key['UserName']
                    key_notify['AccessKeyId'] =key['AccessKeyId']
                    key_notify['key_age']     =key_age
                    key_notify['last_used']   =non_active_days
                    key_notify['status']      =key['Status']
                    key_notify['key_count']   =count
                    key_details.append(key_notify)
            
            else: 
                key_details.append({
                    'UserName': username,
                    'key_count': 0,
                    'key_age': 'none'
                    })
        except Exception as e:
            print(e)

        return key_details

    ################## To calculate No of days Key is been used and present age of the AccessKey#############
    def time_diff(self,keycreatedtime):
            now  = datetime.datetime.now(datetime.timezone.utc)
            diff = now-keycreatedtime
            return diff.days
            
#############################################################################################################
##                     MAIN LAMBDA FUNCTION                                                                ##
#############################################################################################################
def lambda_handler(event, context):
    secret         = os.getenv('secrets')
    username       = os.getenv('username')
    sns_arn        = os.getenv('sns_arn')
    event_name     = os.getenv('event_name')
    primaryowner   = os.getenv('primaryowner')
    secondaryowner = os.getenv('secondaryowner')
    ccid           = os.getenv('ccid')
    lambda_arn     = os.getenv('lambda_arn')
    rotation_day   = os.getenv('rotation_day')
    flag           = 1

    tags = [
            {
                'Key': 'PrimaryOwner',
                'Value': primaryowner
            },
            {
                'Key': 'SecondaryOwner',
                'Value': secondaryowner
            },
            {
                'Key': 'CostCenterID',
                'Value': ccid
                }
            ]
    try:
        iam_access_key = list_access_keys(username)
        key_details = iam_access_key.list_keys()

        ########## Conditional Statements #######################
        user_details_new = []
        user_details_25  = []
        user_details_35  = []
        for key in key_details:
            key_dict = {}
            if key['key_age'] == 'none':
                key_dict['UserName']  = key['UserName']
                key_dict['key_count'] = key['key_count']
                flag = 0
                user_details_new.append(key_dict)

            if key['key_age'] == 25:
                key_dict['UserName'] = key['UserName']
                key_dict['AccessKeyId'] = key['AccessKeyId']
                key_dict['last_used'] = key['last_used']
                user_details_25.append(key_dict)
                key_dict = {}

            if key['key_age'] == 35:
                key_dict['UserName']    = key['UserName']
                key_dict['AccessKeyId'] = key['AccessKeyId']
                key_dict['key_age']     = key['key_age']
                key_dict['last_used']   = key['last_used']
                user_details_35.append(key_dict)
                key_dict = {}

        ########################## create new access key ####################################
        if user_details_25 == [] and user_details_35 == []:
            create_new_keys = access_key_creation(user_details_new, secret,event_name, sns_arn, tags, flag, lambda_arn, rotation_day)
            create_new_keys.create_new_access_key()
        ########################## rotate access keys of the age 25 #########################
        if user_details_25 != []:
            rotate_keys = access_key_creation(user_details_25, secret,event_name, sns_arn, tags, flag, lambda_arn, rotation_day)
            rotate_keys.create_new_access_key()

        ########################## deactivate access keys of the age 35 #####################
        if user_details_35 != []:
            cleanup_keys = iam_credentials_cleanup(secret, user_details_35, sns_arn)
            cleanup_keys.old_keys_cleanup()

    except Exception as e:
        print(e)
    return "lambda execution has completed successfully."
