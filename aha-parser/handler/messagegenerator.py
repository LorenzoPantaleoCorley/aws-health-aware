import json
import boto3
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
import os
import re
import sys
import time

def get_message_for_email(event_details, affected_org_accounts, affected_org_entities, event_type):
    if event_type == "create":
        BODY_HTML = f"""
        <html>
            <body>
                <h>Hello from AWS Health Aware,</h><br>
                <p>There is an AWS incident that is in effect which may likely impact your resources. Here are the details:<br><br>
                <b>Account(s):</b> {affected_org_accounts}<br>
                <b>Account(s):</b> {event_details['successfulSet'][0]['awsAccountId']}<br>
                <b>Service:</b> {event_details['successfulSet'][0]['event']['service']}<br>
                <b>Region:</b> {event_details['successfulSet'][0]['event']['region']}<br>
                <b>Start Time (UTC):</b> {cleanup_time(event_details['successfulSet'][0]['event']['startTime'])}<br>                
                <b>Status:</b> {event_details['successfulSet'][0]['event']['statusCode']}<br>
                <b>Event ARN:</b> {event_details['successfulSet'][0]['event']['arn']}<br> 
                <b>Updates:</b> {event_details['successfulSet'][0]['eventDescription']['latestDescription']}<br><br>
                For updates, please visit the <a href=https://status.aws.amazon.com>AWS Service Health Dashboard</a><br>
                If you are experiencing issues related to this event, please open an <a href=https://console.aws.amazon.com/support/home>AWS Support</a> case within your account.<br><br>
                Thanks, <br><br>AHA: AWS Health Aware
                </p>
            </body>
        </html>
    """
    # elif event_type == "not_managed":
    #     BODY_HTML = f"""
    #     <html>
    #         <body>
    #             <h>Hello from AWS Health Aware,</h><br>
    #             <p>here is an AWS incident that is in effect which may likely impact your resources. <b>Affected account is not under managed OU.</b> Here are the details:<br><br>
    #             <b>Account(s):</b> {affected_org_accounts}<br>
    #             <b>Resource(s):</b> {affected_org_entities}<br>                            
    #             <b>Account(s):</b> {event_details['successfulSet'][0]['awsAccountId']}<br>
    #             <b>Service:</b> {event_details['successfulSet'][0]['event']['service']}<br>
    #             <b>Region:</b> {event_details['successfulSet'][0]['event']['region']}<br>
    #             <b>Start Time (UTC):</b> {cleanup_time(event_details['successfulSet'][0]['event']['startTime'])}<br>                
    #             <b>Status:</b> {event_details['successfulSet'][0]['event']['statusCode']}<br>
    #             <b>Event ARN:</b> {event_details['successfulSet'][0]['event']['arn']}<br> 
    #             <b>Updates:</b> {event_details['successfulSet'][0]['eventDescription']['latestDescription']}<br><br>
    #             For updates, please visit the <a href=https://status.aws.amazon.com>AWS Service Health Dashboard</a><br>
    #             If you are experiencing issues related to this event, please open an <a href=https://console.aws.amazon.com/support/home>AWS Support</a> case within your account.<br><br>
    #             Thanks, <br><br>AHA: AWS Health Aware
    #             </p>
    #         </body>
    #     </html>
    # """
    else:
        BODY_HTML = f"""
        <html>
            <body>
                <h>Hello again from AWS Health Aware,</h><br>
                <p>Good news! The AWS Health incident from earlier has now been marked as resolved.<br><br>
                <b>Account(s):</b> {affected_org_accounts}<br>
                <b>Account(s):</b> {event_details['successfulSet'][0]['awsAccountId']}<br>
                <b>Service:</b> {event_details['successfulSet'][0]['event']['service']}<br>
                <b>Region:</b> {event_details['successfulSet'][0]['event']['region']}<br>
                <b>Start Time (UTC):</b> {cleanup_time(event_details['successfulSet'][0]['event']['startTime'])}<br>
                <b>End Time (UTC):</b> {cleanup_time(event_details['successfulSet'][0]['event']['endTime'])}<br>
                <b>Status:</b> {event_details['successfulSet'][0]['event']['statusCode']}<br>                
                <b>Event ARN:</b> {event_details['successfulSet'][0]['event']['arn']}<br>                
                <b>Updates:</b> {event_details['successfulSet'][0]['eventDescription']['latestDescription']}<br><br>  
                If you are still experiencing issues related to this event, please open an <a href=https://console.aws.amazon.com/support/home>AWS Support</a> case within your account.<br><br>                
                <br><br>
                Thanks, <br><br>AHA: AWS Health Aware
                </p>
            </body>
        </html>
    """
    print("Message sent to Email: ", BODY_HTML)
    return BODY_HTML


def cleanup_time(event_time):
    """
    Takes as input a datetime string as received from The AWS Health event_detail call.  It converts this string to a
    datetime object, changes the timezone to EST and then formats it into a readable string to display in Slack.

    :param event_time: datetime string
    :type event_time: str
    :return: A formatted string that includes the month, date, year and 12-hour time.
    :rtype: str
    """
    event_time = datetime.strptime(event_time[:16], '%Y-%m-%d %H:%M')
    return event_time.strftime("%Y-%m-%d %H:%M:%S")


def get_last_aws_update(event_details):
    """
    Takes as input the event_details and returns the last update from AWS (instead of the entire timeline)

    :param event_details: Detailed information about a specific AWS health event.
    :type event_details: dict
    :return: the last update message from AWS
    :rtype: str
    """
    aws_message = event_details['successfulSet'][0]['eventDescription']['latestDescription']
    return aws_message


def format_date(event_time):
    """
    Takes as input a datetime string as received from The AWS Health event_detail call.  It converts this string to a
    datetime object, changes the timezone to EST and then formats it into a readable string to display in Slack.

    :param event_time: datetime string
    :type event_time: str
    :return: A formatted string that includes the month, date, year and 12-hour time.
    :rtype: str
    """
    event_time = datetime.strptime(event_time[:16], '%Y-%m-%d %H:%M')
    return event_time.strftime('%B %d, %Y at %I:%M %p')
