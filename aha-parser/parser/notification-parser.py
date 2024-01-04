import boto3, os, json
from messagegenerator import get_message_for_email

SENDER = os.environ['FROM_EMAIL']
RECIPIENT = os.environ['TO_EMAIL'].split(",")
# AWS_REGION = os.environ['AWS_REGION']
SUBJECT = os.environ['EMAIL_SUBJECT']

orgs = boto3.client('organizations', region_name='eu-central-1')
accounts_paginator = orgs.get_paginator('list_accounts_for_parent')
ou_paginator = orgs.get_paginator('list_organizational_units_for_parent')

parent_ids = ['ou-37bl-nuoyhcb5','ou-37bl-b7dao3w9']

def lambda_handler(event, context):

  account_id = event['successfulSet'][0]['awsAccountId']
  for parent_id in parent_ids:
    for child_account in get_accounts_recursive(parent_id):
      child_account_id = child_account['Id']
      if child_account_id == account_id:
        return {
          'è un account managed. invio notifica' : child_account_id,
          'organization unit' : parent_id
          # validate sender and recipient's email addresses
        }
  return { 
    'account non managed' : account_id
  }

def get_accounts_recursive(parent_id):
  accounts = []
  for page in accounts_paginator.paginate(ParentId=parent_id):
    accounts += page['Accounts']
  for page in ou_paginator.paginate(ParentId=parent_id):
    for ou in page['OrganizationalUnits']:
      accounts += get_accounts_recursive(ou['Id'])
  return accounts

def get_resources_from_entities(affected_entity_array):
    
    resources = []
    
    for entity in affected_entity_array:
        if entity['entityValue'] == "UNKNOWN":
            #UNKNOWN indicates a public/non-accountspecific event, no resources
            pass
        elif entity['entityValue'] != "AWS_ACCOUNT" and entity['entityValue'] != entity['awsAccountId']:
            resources.append(entity['entityValue'])
    return resources

####################################################################################################
############################ PARTE GIA' PRESENTE NELL'HANDLER ORIGINALE ############################
####################################################################################################

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
