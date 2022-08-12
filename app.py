import aws_cdk as cdk

from stacks.stack import SubnetIpsMonitor

app = cdk.App()

SubnetIpsMonitor(app, "subnet-ip-monitor")

app.synth()
