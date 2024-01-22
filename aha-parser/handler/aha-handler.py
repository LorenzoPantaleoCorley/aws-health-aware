import boto3, os, json
from messagegenerator import get_message_for_email
from urllib.request import URLError, HTTPError
from datetime import datetime, timedelta
from botocore.config import Config
from botocore.exceptions import ClientError
import socket
from dateutil import parser

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

parent_ids = os.environ['IN_SCOPE_OUS']
parent_ids = ['ou-37bl-nuoyhcb5','ou-37bl-b7dao3w9']

def main(event, context):
  print("THANK YOU FOR CHOOSING AWS HEALTH AWARE!")
  # get event details
  health_client = get_sts_token("health")
  describe_events(health_client)

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

def describe_events(health_client):
  str_ddb_format_sec = "%s"
  health_event_type = os.environ["HEALTH_EVENT_TYPE"]
  # set hours to search back in time for events
  delta_hours = os.environ["EVENT_SEARCH_BACK"]
  delta_hours = int(delta_hours)
  time_delta = datetime.now() - timedelta(hours=delta_hours)

# FAR IN MODO CHE IL SEARCHBACK POSSA ESSERE SETTATO IN MINUTI
  # delta_minutes = os.environ["EVENT_SEARCH_BACK"]
  # delta_minutes = int(delta_minutes)
  # time_delta = datetime.now() - timedelta(minutes=delta_minutes)
  print("Searching for events and updates made after: ", time_delta)

  dict_regions = os.environ["REGIONS"]

  # str_filter = {"lastUpdatedTimes": [{"from": time_delta}]}
  str_filter = {"lastUpdatedTime": {"from": time_delta}}

  if health_event_type == "issue":
    event_type_filter = {"eventTypeCategories": ["issue", "investigation"]}
    print(
      "AHA will be monitoring events with event type categories as 'issue' only!"
    )
    str_filter.update(event_type_filter)

  if dict_regions != "all regions":
    dict_regions = [region.strip() for region in dict_regions.split(",")]
    print(
      "AHA will monitor for events only in the selected regions: ", dict_regions
    )
    region_filter = {"regions": dict_regions}
    str_filter.update(region_filter)

  # event_paginator = health_client.get_paginator("describe_events")
  event_paginator = health_client.get_paginator("describe_events_for_organization")
  event_page_iterator = event_paginator.paginate(filter=str_filter)
  for response in event_page_iterator:
    events = response.get("events", [])
    aws_events = json.dumps(events, default=myconverter)
    aws_events = json.loads(aws_events)
    print("Event(s) Received: ", json.dumps(aws_events))
    if len(aws_events) > 0:  # if there are new event(s) from AWS
      for event in aws_events:
        event_arn = event["arn"]
        status_code = event["statusCode"]
        str_update = parser.parse((event["lastUpdatedTime"]))
        str_update = str_update.strftime(str_ddb_format_sec)

        # get organizational view requirements
        affected_org_accounts = get_health_org_accounts(
            health_client, event, event_arn
        )

        if affected_org_accounts != []:
            print("Focused list is ", affected_org_accounts)
            update_org_ddb_flag = True

        affected_org_entities = get_affected_entities(
            health_client, event_arn, affected_org_accounts, is_org_mode=True
        )

        # get event details
        event_details = json.dumps(
          describe_org_event_details(
              health_client, event_arn, affected_org_accounts
          ),
          default=myconverter,
        )
        event_details = json.loads(event_details)
        print("Event Details: ", event_details)
        if event_details["successfulSet"] == []:
          print(
            "An error occured with account:",
            event_details["failedSet"][0]["awsAccountId"],
            "due to:",
            event_details["failedSet"][0]["errorName"],
            ":",
            event_details["failedSet"][0]["errorMessage"],
          )
          continue
        else:
          # write to dynamoDB for persistence
          if update_org_ddb_flag:
            for account_id in affected_org_accounts:
              for parent_id in parent_ids:
                for child_account in get_accounts_recursive(parent_id):
                  # if status_code != "closed":
                  #   event_type = "create"
                  # else:
                  #   event_type="resolve"
                  child_account_id = child_account['Id']
                  if child_account_id == account_id:
                    if "none@domain.com" not in SENDER and RECIPIENT:
                      try:
                        print("Sending the alert to the emails")
                        #get the list of resources from the array of affected entities
                        resources = get_resources_from_entities(affected_org_entities)
                        update_org_ddb(event_arn, str_update, status_code, event_details, affected_org_accounts, resources)
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
              # resources = get_resources_from_entities(affected_entities)
              status_code="not_managed"
              update_org_ddb(event_arn, str_update, status_code, event_details, affected_org_accounts, resources)
              return { 
                'account non managed' : account_id
              }
    else:
        print("No events found in time frame, checking again in 1 minute.")

# organization view affected accounts
def get_health_org_accounts(health_client, event, event_arn):
  affected_org_accounts = []
  event_accounts_paginator = health_client.get_paginator(
    "describe_affected_accounts_for_organization"
  )
  event_accounts_page_iterator = event_accounts_paginator.paginate(eventArn=event_arn)
  for event_accounts_page in event_accounts_page_iterator:
    json_event_accounts = json.dumps(event_accounts_page, default=myconverter)
    parsed_event_accounts = json.loads(json_event_accounts)
    affected_org_accounts = affected_org_accounts + (
      parsed_event_accounts["affectedAccounts"]
    )
  return affected_org_accounts

def get_accounts_recursive(parent_id):
  accounts = []
  for page in accounts_paginator.paginate(ParentId=parent_id):
    accounts += page['Accounts']
  for page in ou_paginator.paginate(ParentId=parent_id):
    for ou in page['OrganizationalUnits']:
      accounts += get_accounts_recursive(ou['Id'])
  return accounts

def send_email(event_details, affected_org_accounts, affected_org_entities, eventType):
  BODY_HTML = get_message_for_email(event_details, affected_org_accounts, affected_org_entities, eventType)
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

def describe_org_event_details(health_client, event_arn, affected_org_accounts):
  if len(affected_org_accounts) >= 1:
    affected_account_ids = affected_org_accounts[0]
    response = health_client.describe_event_details_for_organization(
      organizationEventDetailFilters=[
        {"awsAccountId": affected_account_ids, "eventArn": event_arn}
      ]
    )
  else:
    response = describe_event_details(health_client, event_arn)

  return response

def describe_event_details(health_client, event_arn):
  response = health_client.describe_event_details(
    eventArns=[event_arn],
  )
  return response

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

# def getAccountIDs():
#     account_ids = ""
#     key_file_name = os.environ["ACCOUNT_IDS"]
#     print("Key filename is - ", key_file_name)
#     if os.path.splitext(os.path.basename(key_file_name))[1] == ".csv":
#         s3 = boto3.client("s3")
#         data = s3.get_object(Bucket=os.environ["S3_BUCKET"], Key=key_file_name)
#         account_ids = [account.decode("utf-8") for account in data["Body"].iter_lines()]
#     else:
#         print("Key filename is not a .csv file")
#     print(account_ids)
#     return account_ids

# For Customers using AWS Organizations
def update_org_ddb(
  event_arn,
  str_update,
  status_code,
  event_details,
  affected_org_accounts,
  affected_org_entities,
):
  # open dynamoDB
  dynamodb = boto3.resource("dynamodb")
  ddb_table = os.environ["DYNAMODB_TABLE"]
  aha_ddb_table = dynamodb.Table(ddb_table)
  event_latestDescription = event_details["successfulSet"][0]["eventDescription"][
    "latestDescription"
  ]
  # set time parameters
  delta_hours = os.environ["EVENT_SEARCH_BACK"]
  delta_hours = int(delta_hours)
  delta_hours_sec = delta_hours * 3600

  # formatting time in seconds
  srt_ddb_format_full = "%Y-%m-%d %H:%M:%S"
  str_ddb_format_sec = "%s"
  sec_now = datetime.strftime(datetime.now(), str_ddb_format_sec)

  # check if event arn already exists
  try:
    response = aha_ddb_table.get_item(Key={"arn": event_arn})
  except ClientError as e:
    print(e.response["Error"]["Message"])
  else:
    is_item_response = response.get("Item")
    if is_item_response == None:
      print(datetime.now().strftime(srt_ddb_format_full) + ": record not found")
      # write to dynamodb
      response = aha_ddb_table.put_item(
        Item={
          "arn": event_arn,
          "lastUpdatedTime": str_update,
          "added": sec_now,
          "ttl": int(sec_now) + delta_hours_sec + 86400,
          "statusCode": status_code,
          "affectedAccountIDs": affected_org_accounts,
          "latestDescription": event_latestDescription
          # Cleanup: DynamoDB entry deleted 24 hours after last update
        }
      )
      affected_org_accounts_details = [
        f"{get_account_name(account_id)} ({account_id})"
        for account_id in affected_org_accounts
      ]
      # send to configured endpoints
      if status_code != "closed":
        if status_code != "not_managed":
          send_email(event_details, affected_org_accounts, affected_org_entities, "create")
        else:
          print('Affected account NOT in scope. Notifications will NOT be sent')
      else:
        send_email(event_details, affected_org_accounts, affected_org_entities, "resolve")

    else:
      item = response["Item"]
      if item["lastUpdatedTime"] != str_update and (
        item["statusCode"] != status_code
        or item["latestDescription"] != event_latestDescription
        or item["affectedAccountIDs"] != affected_org_accounts
      ):
        print(
          datetime.now().strftime(srt_ddb_format_full)
          + ": last Update is different"
        )
        # write to dynamodb
        response = aha_ddb_table.put_item(
          Item={
            "arn": event_arn,
            "lastUpdatedTime": str_update,
            "added": sec_now,
            "ttl": int(sec_now) + delta_hours_sec + 86400,
            "statusCode": status_code,
            "affectedAccountIDs": affected_org_accounts,
            "latestDescription": event_latestDescription
            # Cleanup: DynamoDB entry deleted 24 hours after last update
          }
        )
        affected_org_accounts_details = [
          f"{get_account_name(account_id)} ({account_id})"
          for account_id in affected_org_accounts
        ]
        # send to configured endpoints
        if status_code != "closed":
          send_email(
            event_details,
            affected_org_accounts_details,
            affected_org_entities,
            event_type="create",
          )
        else:
          send_email(
            event_details,
            affected_org_accounts_details,
            affected_org_entities,
            event_type="resolve",
          )
      else:
        print("No new updates found, checking again in 1 minute.")
