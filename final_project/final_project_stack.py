from aws_cdk import (
    core as cdk,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_rds as rds,
    aws_elasticloadbalancingv2 as elbv2,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
    aws_certificatemanager as acm,
)


class FinalProjectStack(cdk.Stack):
    def __init__(self, scope: cdk.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a VPC with public and private subnets
        vpc = ec2.Vpc(self, "MyVPC", max_azs=2, cidr="10.0.0.0/16",
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_NAT, cidr_mask=24)
            ]
        )
        
        # Create an ECS cluster
        cluster = ecs.Cluster(self, "MyCluster", vpc=vpc)

        # Create a Fargate task definition for the Minecraft server
        task_definition = ecs.FargateTaskDefinition(
            self,
            "MyTaskDefinition",
            memory_limit_mib=2048,
            cpu=1024,
        )

        # Add a container to the task definition
        container = task_definition.add_container(
            "MyContainer",
            image=ecs.ContainerImage.from_registry("itzg/minecraft-server"),
            port_mappings=[ecs.PortMapping(container_port=25565)],
        )

        # Create an ECS service with Fargate
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "MyService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            listener_port=80,
            public_load_balancer=True,
            assign_public_ip=True,
        )

        # Create an Application Load Balancer
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "MyALB",
            vpc=vpc,
            internet_facing=True,
        )

        # Create a listener for the load balancer
        listener = alb.add_listener(
            "MyListener",
            port=80,
            open=True,
            default_action=elbv2.ListenerAction.forward([service.target_group])
        )


        # Configure Auto Scaling for the service
        scalable_target = service.service.auto_scale_task_count(min_capacity=1, max_capacity=3)
        scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=50,
        )

        # Configure security group to allow traffic on port 25565
        service.service.connections.allow_from_any_ipv4(ec2.Port.tcp(25565))

        db_cluster = rds.DatabaseCluster(
            self,
            "MyDatabaseCluster",
            engine=rds.DatabaseClusterEngine.aurora_mysql(
                version=rds.AuroraMysqlEngineVersion.VER_2_11_2  # Updated version
            ),
            instances=2,  # Number of instances in the cluster
            default_database_name="MinecraftDB",
            instance_props=rds.InstanceProps(  # Specify instance properties here
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE2, ec2.InstanceSize.SMALL),
                vpc=vpc
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Configure security group to allow traffic from the Minecraft server to the database
        db_cluster.connections.allow_from(service.service, ec2.Port.tcp(3306))

        # Define a domain name for the Minecraft server
        domain_name = "allynak.infracourse.cloud"  # Replace with your desired domain name

        # Create a hosted zone for the domain
        hosted_zone = route53.HostedZone.from_lookup(
            self,
            "MyHostedZone",
            domain_name=domain_name,
        )

        # Create an SSL/TLS certificate for the domain
        certificate = acm.Certificate(
            self,
            "MyCertificate",
            domain_name="allynak.infracourse.cloud",
            subject_alternative_names=[
                "*.allynak.infracourse.cloud",
                "*.yoctogram.allynak.infracourse.cloud"
            ],
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        # Create an HTTPS listener for the load balancer
        https_listener = alb.add_listener(
            "MyHTTPSListener",
            port=443,
            certificates=[certificate],
        )

        # Configure the HTTPS listener to forward traffic to the target group
        https_listener.add_target_groups(
            "MyTargetGroup",
            target_groups=[service.target_group],
        )

        # Create an A record for the domain pointing to the load balancer
        route53.ARecord(
            self,
            "MyARecord",
            record_name=domain_name,
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(route53_targets.LoadBalancerTarget(alb)),
        )
