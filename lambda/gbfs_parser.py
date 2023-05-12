import json
import logging
import os
import boto3
import urllib.request
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

timestamp = datetime.utcnow().strftime("%Y%m%d_%H:%M:%S")
QUEUE_URL = os.getenv("QUEUE_URL")
QUEUE_ARN = os.getenv("QUEUE_ARN")
BUCKET_NAME = os.getenv("BUCKET_NAME")
EVENT_RULE_ARN = os.getenv("EVENT_RULE_ARN")

sqs = boto3.client("sqs")
s3 = boto3.resource("s3")


def add_metadata(bike):
    bike["timestamp"] = timestamp
    bike["tags"] = {
        "is_disabled": bike["is_disabled"],
        "is_reserved": bike["is_reserved"],
        "timestamp": timestamp,
    }
    return bike


def parse_url_and_push_to_sqs():
    url = "https://mds.bird.co/gbfs/tempe/free_bike_status.json"
    logger.info(f"Getting bikes from url {url}")
    res = urllib.request.urlopen(
        urllib.request.Request(
            url=url,
            headers={"Accept": "application/json"},
            method="GET",
        ),
        timeout=10,
    )
    if res.status == 200:
        data = json.loads(res.read())["data"]
        bikes = data["bikes"]
        logger.info(f"Processing {len(bikes)} bikes")
        for bike in bikes:
            bike = add_metadata(bike)
            message_body = {"bike": bike}
            response = sqs.send_message(
                QueueUrl=QUEUE_URL, MessageBody=json.dumps(message_body)
            )
            logger.info(f"Message {response['MessageId']} sent to SQS queue")
            # # TO REMOVE
            # exit(0)

    else:
        logger.error(f"Error fetching data from {url}, status code {res.status}")


def get_from_sqs_and_push_to_s3(data):
    bike = json.loads(data)["bike"]
    bike_id = bike["bike_id"]
    bike = add_metadata(bike)
    file_name = f"{bike_id}.json"
    file_content = json.dumps(bike)
    object = s3.Object(BUCKET_NAME, file_name)
    object.put(
        Body=file_content,
        Tagging=f"timestamp={timestamp}&is_disabled={bike['is_disabled']}&is_reserved={bike['is_reserved']}",
    )
    logger.info(f"S3 object {file_name} saved")


def main(event, context):
    # logger.debug(f"DEBUG event: {event}")
    if (
        "source" in event
        and event["source"] == "aws.events"
        and "detail-type" in event
        and event["detail-type"] == "Scheduled Event"
        and "resources" in event
        and event["resources"][0] == EVENT_RULE_ARN
    ):
        logger.info(f"Lambda triggered by {EVENT_RULE_ARN} cron")
        parse_url_and_push_to_sqs()
    elif (
        "Records" in event
        and len(event["Records"]) > 0
        and "eventSourceARN" in event["Records"][0]
        and event["Records"][0]["eventSourceARN"] == QUEUE_ARN
    ):
        logger.info(f"Lambda triggered by SQS message event")
        get_from_sqs_and_push_to_s3(event["Records"][0]["body"])
    else:
        logger.error("Unknown event source")
        exit(1)
