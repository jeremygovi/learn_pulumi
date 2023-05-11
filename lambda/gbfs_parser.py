import json


def main(event, context):
    return {"statusCode": 200, "body": json.dumps("Cheers from AWS Lambda!!")}
