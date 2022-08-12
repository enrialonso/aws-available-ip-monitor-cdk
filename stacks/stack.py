import aws_cdk
import boto3
from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_action,
    aws_sns as sns,
)
from constructs import Construct

ALARM_THERSHOLD = 50


class SubnetIpsMonitor(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpcs = self.node.try_get_context("vpcs")
        self.email_subscriptions = self.node.try_get_context("emailSubscription")
        self.alarm_namespace = "IP Subnet Monitor"
        self.prefix_metric_name = "Used IP's"
        self.alarm_threshold = self.node.try_get_context("alarmThreshold")

        # IAM
        self.lambda_role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name="lambda-subnet-ip-monitor-role",
        )

        self.lambda_role.add_managed_policy(
            policy=iam.ManagedPolicy.from_managed_policy_arn(
                self,
                "LambdaExecutionRole",
                managed_policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            )
        )

        # Role Policy CloudWatch
        self.lambda_role.add_to_policy(
            statement=iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"], effect=iam.Effect.ALLOW, resources=["*"]
            )
        )

        # Role Policy VPC
        self.lambda_role.add_to_policy(
            statement=iam.PolicyStatement(
                actions=["ec2:DescribeVpcs", "ec2:DescribeSubnets"], effect=iam.Effect.ALLOW, resources=["*"]
            )
        )

        # Function
        self.lambda_monitor = lambda_.Function(
            self,
            "LambdaVPCIpMonitor",
            function_name="lambda-subnet-ip-monitor",
            description="Lambda to monitor available ips on subnets",
            code=lambda_.Code.from_asset("./lambda"),
            handler="main.handler",
            runtime=lambda_.Runtime.PYTHON_3_9,
            architecture=lambda_.Architecture.X86_64,
            role=self.lambda_role,
            timeout=aws_cdk.Duration.seconds(60),
            environment={
                "REGION": self.region,
                "SELECTED_VPC": self.vpcs,
                "ALARM_NAMESPACE": self.alarm_namespace,
                "PREFIX_METRIC_NAME": self.prefix_metric_name,
            },
        )

        # EventBridge Rule for trigger lambda
        self.cron_rule = events.Rule(
            self,
            "LambdaCronRule",
            enabled=True,
            rule_name="lambda-subnet-ip-monitor-rule",
            schedule=events.Schedule.rate(aws_cdk.Duration.minutes(1)),
        )
        self.cron_rule.add_target(target=targets.LambdaFunction(self.lambda_monitor))

        # SNS for send Alarms
        sns_name = "subnet-ip-monitor-sns-alarm"
        self.alarm_sns = sns.Topic(self, "AlarmSns", display_name=sns_name, topic_name=sns_name)
        for email in self.email_subscriptions.split(","):
            sns.Subscription(
                self,
                "subnet-ip-monitor-sns-subscription-alarm",
                topic=self.alarm_sns,
                endpoint=email,
                protocol=sns.SubscriptionProtocol.EMAIL,
            )

        # Build all alarms for selected subnets of vpc
        for subnet in self.get_subnet_ids():
            metric = cloudwatch.Metric(
                namespace=self.alarm_namespace,
                metric_name=f"{self.prefix_metric_name} - {subnet['subnet']}",
                label=f"{self.prefix_metric_name} - {subnet['subnet']}",
                dimensions_map={"Subnets": subnet['subnet']},
                period=aws_cdk.Duration.minutes(1),
                unit=cloudwatch.Unit.PERCENT,
            )
            alarm = cloudwatch.Alarm(
                self,
                f"VpcSubnetMonitorAvailableIps-{subnet['subnet']}",
                alarm_name=f"Alarm Vpc: {subnet['vpc']} Subnet: {subnet['subnet']}",
                metric=metric,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                threshold=self.alarm_threshold,
                evaluation_periods=1,
            )
            alarm.add_alarm_action(cloudwatch_action.SnsAction(self.alarm_sns))

    def get_subnet_ids(self):
        ec2 = boto3.client("ec2")
        subnet_ids = []
        if self.node.try_get_context("vpcs") == "all":
            vpc_raw = ec2.describe_vpcs(
                Filters=[
                    {
                        "Name": "state",
                        "Values": [
                            "available",
                        ],
                    },
                ]
            )
            vpc_ids = [item["VpcId"] for item in vpc_raw["Vpcs"]]
        else:
            vpc_ids = [item for item in self.vpcs.split(",")]

        ec2_resources = boto3.resource("ec2")
        for vpc_id in vpc_ids:
            vpc_info = ec2_resources.Vpc(vpc_id)
            for subnet in vpc_info.subnets.all():
                subnet_ids.append({"vpc": vpc_id, "subnet": subnet.id})

        return subnet_ids
