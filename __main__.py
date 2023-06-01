import pulumi
import pulumi_aws as aws

# Vars definition
event_target_name = "gbfs-cron-lambda-target"
cron_trigger_enabled = False
lambda_sqs_to_s3_batch_size = 1
lambda_execution_timeout = 60
sqs_messages_retention = 1209600  # the max value (need resilience)
alarm_enabled = False

##################
## S3 Bucket
##################
bucket = aws.s3.Bucket(
    "poc-gbfs-payload",
    # bucket="poc-gbfs-payload",
    acl="private",
    versioning=aws.s3.BucketVersioningArgs(
        enabled=True,
    ),
)
# Export the name of the bucket
pulumi.export("bucket_name", bucket.bucket)


######################################################
## SQS Queue (for scaling / higer performances)
######################################################
queue = aws.sqs.Queue(
    "gbfs-queue",
    message_retention_seconds=sqs_messages_retention,
    visibility_timeout_seconds=lambda_execution_timeout,
)
pulumi.export("queue_name", queue.name)


##################
## IAM Stuff
##################
lambda_role = aws.iam.Role(
    "gbfsLambdaRole",
    assume_role_policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Effect": "Allow",
                "Sid": ""
            }
        ]
    }""",
)

arns = pulumi.Output.all(bucket.arn, queue.arn)
lambda_role_policy = aws.iam.RolePolicy(
    "gbfsLambdaRolePolicy",
    role=lambda_role.id,
    policy=arns.apply(
        lambda arns: f"""{{
            "Version": "2012-10-17",
            "Statement": [
                {{
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:*"
                }},
                {{
                    "Effect": "Allow",
                    "Action": "s3:*",
                    "Resource": [
                        "{arns[0]}/*",
                        "{arns[0]}"
                    ]
                }},
                {{
                    "Effect": "Allow",
                    "Action": [
                        "sqs:SendMessage",
                        "sqs:ReceiveMessage",
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes"
                    ],
                    "Resource": "{arns[1]}"
                }}
            ]
        }}"""
    ),
)


####################################
## Event rule (cloudwatch part)
####################################

event_rule = aws.cloudwatch.EventRule(
    "trigger-every-minute-rule",
    schedule_expression="rate(1 minute)",
    is_enabled=cron_trigger_enabled,
)

##################
## Lambda Function
##################

lambda_func = aws.lambda_.Function(
    "gbfs-parser",
    role=lambda_role.arn,
    runtime="python3.8",
    handler="gbfs_parser.main",
    code=pulumi.AssetArchive({".": pulumi.FileArchive("./lambda")}),
    environment={
        "variables": {
            "BUCKET_NAME": bucket.id,
            "QUEUE_URL": queue.url,
            "QUEUE_ARN": queue.arn,
            "EVENT_RULE_ARN": event_rule.arn,
        }
    },
    timeout=lambda_execution_timeout,
)


####################################
## Event Target (cloudwatch part)
####################################

event_target = aws.cloudwatch.EventTarget(
    event_target_name,
    rule=event_rule.name,
    arn=lambda_func.arn,
)

# Allow cloudwatch to call lambda
cloudwatch_to_lambda_permission = aws.lambda_.Permission(
    "gbfs-lambda-cloudwatch-permission",
    action="lambda:InvokeFunction",
    function=lambda_func.name,
    principal="events.amazonaws.com",
    source_arn=event_rule.arn,
)

############################
## SNS Mail notification
############################
alarm_topic = aws.sns.Topic("gbfs-parser-errors")
alarm_email = aws.sns.TopicSubscription(
    "jgovi-email",
    topic=alarm_topic.arn,
    protocol="email",
    endpoint="xxx@gmail.com",
)

############################
## Cloudwatch Alarm
############################
alarm = aws.cloudwatch.MetricAlarm(
    "gbfs-parser-alarm",
    alarm_description="Alert for gbfs-parser errors",
    comparison_operator="GreaterThanThreshold",
    evaluation_periods=1,
    metric_name="Errors",
    namespace="AWS/Lambda",
    period=60,
    statistic="Sum",
    threshold=0,
    actions_enabled=alarm_enabled,
    alarm_actions=[alarm_topic.arn],
    dimensions={"FunctionName": lambda_func.name},
)

############################
## EventSourceMapping
############################
# Trigger the lambda function when there are messages in the SQS queue
lambda_event_source_mapping = aws.lambda_.EventSourceMapping(
    "sqs-to-lambda-event-source-mapping",
    event_source_arn=queue.arn,
    function_name=lambda_func.arn,
    batch_size=lambda_sqs_to_s3_batch_size,
)
