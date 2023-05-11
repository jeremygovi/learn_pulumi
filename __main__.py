import pulumi
import pulumi_aws as aws

##################
## S3 Bucket
##################
bucket = aws.s3.Bucket(
    "poc-gbfs-payload",
    bucket="poc-gbfs-payload",
    acl="private",
    versioning=aws.s3.BucketVersioningArgs(
        enabled=True,
    ),
)
# Export the name of the bucket
pulumi.export("bucket_name", bucket.bucket)


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

lambda_role_policy = aws.iam.RolePolicy(
    "gbfsLambdaRolePolicy",
    role=lambda_role.id,
    policy=pulumi.Output.all(bucket.arn).apply(
        lambda arn: f"""{{
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
                        "{arn[0]}/*",
                        "{arn[0]}"
                    ]
                }}
            ]
        }}"""
    ),
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
)


####################################
## Lambda trigger (cloudwatch part)
####################################

event_rule = aws.cloudwatch.EventRule(
    "trigger-every-minute-rule",
    schedule_expression="rate(1 minute)",
    is_enabled=False,
)

event_target = aws.cloudwatch.EventTarget(
    "gbfs-lambda-target",
    rule=event_rule.name,
    arn=lambda_func.arn,
)

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
    endpoint="jeremygovi@gmail.com",
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
    actions_enabled=True,
    alarm_actions=[alarm_topic.arn],
    dimensions={"FunctionName": lambda_func.name},
)
