"""
Lambda ETL Trigger — dispara ECS RunTask para correr el ETL.

Recibe un evento de EventBridge. Lee los tickers de etl_universe.txt
(bundleado en el zip de la Lambda) y los pasa como --assets al ETL.

La task ECS corre el ETL real (puede durar >15 min, sin limite).
Lambda solo es el boton — termina en <2 segundos.
"""

import json
import logging
from pathlib import Path
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs", region_name="us-east-2")

CLUSTER = "financial-data"
TASK_DEFINITION = "financial-data-etl"
SUBNETS = [
    "subnet-0685a1cd4c6dbea34",
    "subnet-04096d910b56372fd",
    "subnet-0b515ac89b9fbf99b",
]
SECURITY_GROUPS = ["sg-0420f49957d8f8159"]

# Lee los tickers del .txt bundleado junto con este .py
UNIVERSE_FILE = Path(__file__).parent / "etl_universe.txt"
TICKERS = UNIVERSE_FILE.read_text().strip().split()


def handler(event, context):
    logger.info(f"ETL trigger received — {len(TICKERS)} tickers from etl_universe.txt")

    # El comando que ECS va a ejecutar:
    # python -m financial_data_etl.main_runner --assets AAPL AMZN AVGO ...
    command = ["--assets"] + TICKERS

    response = ecs.run_task(
        cluster=CLUSTER,
        taskDefinition=TASK_DEFINITION,
        launchType="FARGATE",
        networkConfiguration={
            # Subnets y security groups obligatorios en Fargate
            "awsvpcConfiguration": {
                "subnets": SUBNETS,
                "securityGroups": SECURITY_GROUPS,
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            # containerOverrides.command se concatena al entryPoint de la task def
            # entryPoint = ["python", "-m", "financial_data_etl.main_runner"]
            # command = ["--assets", "AAPL", "AMZN", ...]
            # resultado: python -m financial_data_etl.main_runner --assets AAPL AMZN ...
            "containerOverrides": [
                {
                    "name": "etl",
                    "command": command,
                }
            ]
        },
    )

    task_arns = [t["taskArn"] for t in response.get("tasks", [])]
    failures = response.get("failures", [])

    logger.info(f"RunTask response — tasks: {task_arns}, failures: {failures}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "tasks": task_arns,
            "failures": failures,
        }),
    }
