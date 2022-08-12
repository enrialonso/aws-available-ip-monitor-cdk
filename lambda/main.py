import ipaddress
import os
from typing import List, Dict

import boto3

REGION = os.getenv("REGION", "eu-west-1")
SELECTED_VPC = os.getenv("SELECTED_VPC", "vpc-01e52581bab413b49")

ec2 = boto3.client("ec2", region_name=REGION)
ec2_resources = boto3.resource("ec2")
cloudwatch = boto3.client("cloudwatch")


def get_vpc_ids() -> List[Dict]:
    if SELECTED_VPC == "all":
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
        return [{"id": item["VpcId"]} for item in vpc_raw["Vpcs"]]
    else:
        return [{"id": item} for item in SELECTED_VPC.split(",")]


def send_cloudwatch_metrics(subnet_id: str, used_ips_percentage: float) -> None:
    cloudwatch.put_metric_data(
        Namespace="IP Subnet Monitor",
        MetricData=[
            {
                "MetricName": f"Used IP's - {subnet_id}",
                "Dimensions": [
                    {"Name": "Subnets", "Value": subnet_id},
                ],
                "Value": used_ips_percentage,
                "Unit": "Percent",
                "StorageResolution": 60,
            },
        ],
    )


def handler(event, context):
    for vpc in get_vpc_ids():
        print(f"VPC ID >> {vpc['id']}")
        vpc_info = ec2_resources.Vpc(vpc["id"])
        for subnet in vpc_info.subnets.all():
            total_ips_cidr = ipaddress.ip_network(subnet.cidr_block).num_addresses
            total_ips_available_subnet = subnet.available_ip_address_count
            used_ips = total_ips_cidr - total_ips_available_subnet
            used_ips_percentage = 100 - ((total_ips_available_subnet * 100) / total_ips_cidr)
            msg = f"\tSubnet id: {subnet.id} Total Ips Subnet: {total_ips_cidr}, Available: {total_ips_available_subnet}, IP Used: {used_ips} - {used_ips_percentage:.1f} %"
            print(msg)
            send_cloudwatch_metrics(subnet.id, used_ips_percentage)
