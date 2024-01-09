import boto3, os, json
from messagegenerator import get_message_for_email
from urllib.request import URLError, HTTPError
from datetime import datetime, timedelta
from botocore.config import Config
import socket
# query active health API endpoint
health_dns = socket.gethostbyname_ex('global.health.amazonaws.com')
(current_endpoint, global_endpoint, ip_endpoint) = health_dns
health_active_list = current_endpoint.split('.')
health_active_region = health_active_list[1]
print("current health region: ", health_active_region)

SENDER = os.environ['FROM_EMAIL']
RECIPIENT = os.environ['TO_EMAIL'].split(",")
# AWS_REGION = os.environ['AWS_REGION']
SUBJECT = os.environ['EMAIL_SUBJECT']

orgs = boto3.client('organizations', region_name='eu-central-1')
accounts_paginator = orgs.get_paginator('list_accounts_for_parent')
ou_paginator = orgs.get_paginator('list_organizational_units_for_parent')

parent_ids = ['ou-37bl-nuoyhcb5','ou-37bl-b7dao3w9']

def main(event, context):

  # get event details
  health_client = get_sts_token('health')
  # event_arn = event['arn']
  # account_id = event_details['successfulSet'][0]['awsAccountId']
  # status_code = event['statusCode']

  delta_hours = os.environ["EVENT_SEARCH_BACK"]
  delta_hours = int(delta_hours)
  time_delta = datetime.now() - timedelta(hours=delta_hours)
  str_filter = {"lastUpdatedTimes": [{"from": time_delta}]}
  event_paginator = health_client.get_paginator("describe_events")
  event_page_iterator = event_paginator.paginate(filter=str_filter)
  for response in event_page_iterator:
      events = response.get("events", [])
      aws_events = json.dumps(events, default=myconverter)
      aws_events = json.loads(aws_events)
      print("Event(s) Received: ", json.dumps(aws_events))
      if len(aws_events) > 0:  # if there are new event(s) from AWS
          for event in aws_events:

            event_arn = event['successfulSet'][0]['event']['arn']
            event_details = json.dumps(describe_event_details(health_client, event_arn), default=myconverter)
            event_details = json.loads(event_details)
            account_id = event['successfulSet'][0]['awsAccountId']
            status_code = event['successfulSet'][0]['event']['statusCode']
            event_details = json.dumps(describe_event_details(health_client, event_arn), default=myconverter)
            event_details = json.loads(event_details)

            # get non-organizational view requirements
            affected_accounts = get_health_accounts(health_client, event, event_arn)
            affected_entities = get_affected_entities(health_client, event_arn, affected_accounts, is_org_mode = False)

            for parent_id in parent_ids:
              for child_account in get_accounts_recursive(parent_id):
                if status_code != "closed":
                  event_type = "create"
                else:
                  event_type="resolve"
                child_account_id = child_account['Id']
                if child_account_id == account_id:
                  if "none@domain.com" not in SENDER and RECIPIENT:
                    try:
                      print("Sending the alert to the emails")
                      #get the list of resources from the array of affected entities
                      resources = get_resources_from_entities(affected_entities)
                      # send_email(event_details, event_type, affected_accounts, resources)
                      send_email(event, event_type, affected_accounts, resources)
                    except HTTPError as e:
                      print("Got an error while sending message to Email: ", e.code, e.reason)
                    except URLError as e:
                      print("Server connection failed: ", e.reason)
                      pass
                  return {
                    'è un account managed. invio notifica' : child_account_id,
                    'organization unit' : parent_id
                    # validate sender and recipient's email addresses
                  }
            resources = get_resources_from_entities(affected_entities)
            unmanaged_event_type="not_managed"
            send_email(event, unmanaged_event_type, affected_accounts, resources)
            return { 
              'account non managed' : account_id
            }
      else:
          print("No events found in time frame, checking again in 1 minute.")

def get_accounts_recursive(parent_id):
  accounts = []
  for page in accounts_paginator.paginate(ParentId=parent_id):
    accounts += page['Accounts']
  for page in ou_paginator.paginate(ParentId=parent_id):
    for ou in page['OrganizationalUnits']:
      accounts += get_accounts_recursive(ou['Id'])
  return accounts

def send_email(event_details, eventType, affected_accounts, affected_entities):
  BODY_HTML = get_message_for_email(event_details, eventType, affected_accounts, affected_entities)
  client = boto3.client('ses', region_name='eu-central-1')
  response = client.send_email(
    Source=SENDER,
    Destination={
      'ToAddresses': RECIPIENT
    },
    Message={
      'Body': {
        'Html': {
          'Data': BODY_HTML
        },
      },
      'Subject': {
        'Charset': 'UTF-8',
        'Data': SUBJECT,
      },
    },
  )

def get_resources_from_entities(affected_entity_array):
    
    resources = []
    
    for entity in affected_entity_array:
        if entity['entityValue'] == "UNKNOWN":
            #UNKNOWN indicates a public/non-accountspecific event, no resources
            pass
        elif entity['entityValue'] != "AWS_ACCOUNT" and entity['entityValue'] != entity['awsAccountId']:
            resources.append(entity['entityValue'])
    return resources

def myconverter(json_object):
    if isinstance(json_object, datetime):
        return json_object.__str__()

# create a boto3 health client w/ backoff/retry
config = Config(
    region_name=health_active_region,
    retries=dict(
        max_attempts=10  # org view apis have a lower tps than the single
        # account apis so we need to use larger
        # backoff/retry values than than the boto defaults
    )
)
def get_sts_token(service):
    assumeRoleArn = os.environ['ASSUME_ROLE_ARN']
    boto3_client = None
    
    if "arn:aws:iam::" in assumeRoleArn:
        ACCESS_KEY = []
        SECRET_KEY = []
        SESSION_TOKEN = []
        
        sts_connection = boto3.client('sts')
        
        ct = datetime.now()
        role_session_name = "cross_acct_aha_session"
        
        acct_b = sts_connection.assume_role(
          RoleArn=assumeRoleArn,
          RoleSessionName=role_session_name,
          DurationSeconds=900,
        )
        
        ACCESS_KEY    = acct_b['Credentials']['AccessKeyId']
        SECRET_KEY    = acct_b['Credentials']['SecretAccessKey']
        SESSION_TOKEN = acct_b['Credentials']['SessionToken']
        
        # create service client using the assumed role credentials, e.g. S3
        boto3_client = boto3.client(
          service,
          config=config,
          aws_access_key_id=ACCESS_KEY,
          aws_secret_access_key=SECRET_KEY,
          aws_session_token=SESSION_TOKEN,
        )
        print("Running in member account deployment mode")
    else:
        boto3_client = boto3.client(service, config=config)
        print("Running in management account deployment mode")
    
    return boto3_client

# def get_secrets():
#     region_name = os.environ['AWS_REGION']
#     get_secret_value_response_assumerole = ""
#     get_secret_value_response_eventbus = ""
#     get_secret_value_response_chime = ""
#     get_secret_value_response_teams = ""
#     get_secret_value_response_slack = ""
#     event_bus_name = "EventBusName"
#     secret_assumerole_name = "AssumeRoleArn" 

#     # create a Secrets Manager client
#     session = boto3.session.Session()
#     client = session.client(
#         service_name='secretsmanager',
#         region_name=region_name
#     )
#     # Iteration through the configured AWS Secrets
#     try:
#         get_secret_value_response_teams = client.get_secret_value(
#             SecretId=secret_teams_name
#         )
#     except ClientError as e:
#         if e.response['Error']['Code'] == 'AccessDeniedException':
#             print("No AWS Secret configured for Teams, skipping")
#             teams_channel_id = "None"
#         else: 
#             print("There was an error with the Teams secret: ",e.response)
#             teams_channel_id = "None"
#     finally:
#         if 'SecretString' in get_secret_value_response_teams:
#             teams_channel_id = get_secret_value_response_teams['SecretString']
#         else:
#             teams_channel_id = "None"
#     try:
#         get_secret_value_response_slack = client.get_secret_value(
#             SecretId=secret_slack_name
#         )
#     except ClientError as e:
#         if e.response['Error']['Code'] == 'AccessDeniedException':
#             print("No AWS Secret configured for Slack, skipping")
#             slack_channel_id = "None"
#         else:    
#             print("There was an error with the Slack secret: ",e.response)
#             slack_channel_id = "None"
#     finally:
#         if 'SecretString' in get_secret_value_response_slack:
#             slack_channel_id = get_secret_value_response_slack['SecretString']
#         else:
#             slack_channel_id = "None"
#     try:
#         get_secret_value_response_chime = client.get_secret_value(
#             SecretId=secret_chime_name
#         )
#     except ClientError as e:
#         if e.response['Error']['Code'] == 'AccessDeniedException':
#             print("No AWS Secret configured for Chime, skipping")
#             chime_channel_id = "None"
#         else:    
#             print("There was an error with the Chime secret: ",e.response)
#             chime_channel_id = "None"
#     finally:
#         if 'SecretString' in get_secret_value_response_chime:
#             chime_channel_id = get_secret_value_response_chime['SecretString']
#         else:
#             chime_channel_id = "None"
#     try:
#         get_secret_value_response_assumerole = client.get_secret_value(
#             SecretId=secret_assumerole_name
#         )
#     except ClientError as e:
#         if e.response['Error']['Code'] == 'AccessDeniedException':
#             print("No AWS Secret configured for Assume Role, skipping")
#             assumerole_channel_id = "None"
#         else:    
#             print("There was an error with the Assume Role secret: ",e.response)
#             assumerole_channel_id = "None"
#     finally:
#         if 'SecretString' in get_secret_value_response_assumerole:
#             assumerole_channel_id = get_secret_value_response_assumerole['SecretString']
#         else:
#             assumerole_channel_id = "None"    
#     try:
#         get_secret_value_response_eventbus = client.get_secret_value(
#             SecretId=event_bus_name
#         )
#     except ClientError as e:
#         if e.response['Error']['Code'] == 'AccessDeniedException':
#             print("No AWS Secret configured for EventBridge, skipping")
#             eventbus_channel_id = "None"
#         else:    
#             print("There was an error with the EventBridge secret: ",e.response)
#             eventbus_channel_id = "None"
#     finally:
#         if 'SecretString' in get_secret_value_response_eventbus:
#             eventbus_channel_id = get_secret_value_response_eventbus['SecretString']
#         else:
#             eventbus_channel_id = "None"            
#         secrets = {
#             "teams": teams_channel_id,
#             "slack": slack_channel_id,
#             "chime": chime_channel_id,
#             "eventbusname": eventbus_channel_id,
#             "ahaassumerole": assumerole_channel_id
#         }    
#         # uncomment below to verify secrets values
#         #print("Secrets: ",secrets)   
#     return secrets

def describe_event_details(health_client, event_arn):
    response = health_client.describe_event_details(
        eventArns=[event_arn],
    )
    return response

# non-organization view affected accounts
def get_health_accounts(health_client, event, event_arn):
    affected_accounts = []
    event_accounts_paginator = health_client.get_paginator('describe_affected_entities')
    event_accounts_page_iterator = event_accounts_paginator.paginate(
        filter = {
            'eventArns': [
                event_arn
            ]
        }
    )
    for event_accounts_page in event_accounts_page_iterator:
        json_event_accounts = json.dumps(event_accounts_page, default=myconverter)
        parsed_event_accounts = json.loads(json_event_accounts)
        try:
          affected_accounts.append(parsed_event_accounts['entities'][0]['awsAccountId'])
        except Exception:
          affected_accounts = []
    return affected_accounts

# get the array of affected entities for all affected accounts and return as an array of JSON objects
def get_affected_entities(health_client, event_arn, affected_accounts, is_org_mode):  
    affected_entity_array = []

    for account in affected_accounts: 

        if is_org_mode:
            event_entities_paginator = health_client.get_paginator('describe_affected_entities_for_organization')
            event_entities_page_iterator = event_entities_paginator.paginate(
                organizationEntityFilters=[
                    {
                        'awsAccountId': account,
                        'eventArn': event_arn
                    }
                ]
            )
        else:
            event_entities_paginator = health_client.get_paginator('describe_affected_entities')
            event_entities_page_iterator = event_entities_paginator.paginate(
                filter = {
                    'eventArns': [
                        event_arn
                    ]
                }
            )

        for event_entities_page in event_entities_page_iterator:
            json_event_entities = json.dumps(event_entities_page, default=myconverter)
            parsed_event_entities = json.loads(json_event_entities)
            for entity in parsed_event_entities['entities']:                  
                entity.pop("entityArn") #remove entityArn to avoid confusion with the arn of the entityValue (not present)
                entity.pop("eventArn") #remove eventArn duplicate of detail.arn
                entity.pop("lastUpdatedTime") #remove for brevity
                if is_org_mode:
                    entity['awsAccountName'] = get_account_name(entity['awsAccountId'])
                affected_entity_array.append(entity)
    
    return affected_entity_array

# Get Account Name 
def get_account_name(account_id):
    org_client = get_sts_token('organizations')
    try:
        account_name = org_client.describe_account(AccountId=account_id)['Account']['Name']
    except Exception:
        account_name = account_id
    return account_name
