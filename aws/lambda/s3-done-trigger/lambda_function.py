"""
Lambda S3 -> ECS dispatcher (sprint VPS-scrape).

Trigger:  S3 PutObject Event from bucket leonardovila-financial-raw,
          filter prefix=raw/tv/_DONE_, suffix=.txt
Action:   Run ONE ECS Fargate task (financial-data-etl) with overrides
              USE_VPS_RAW=true
              INGESTION_DATE=YYYY-MM-DD (parsed from the marker filename)
          That task lists all the day's data.jsonl.gz under
          raw/tv/symbol=*/ingestion_date={INGESTION_DATE}/, parses them
          back through the existing scraper parsers, persists to RDS
          and computes derivatives — same pipeline as before, just
          fed from S3 instead of from a live WS scrape.

This Lambda must NEVER call ecs.run_task more than once per marker.
The S3 Event filter on _DONE_*.txt is the natural dedupe (the VPS
uploads the marker exactly once per run).
"""
import json
import logging
import os
import re
from urllib.parse import unquote_plus

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-2")
CLUSTER = os.environ.get("ECS_CLUSTER", "financial-data")
TASK_DEFINITION = os.environ.get("ECS_TASK_DEFINITION", "financial-data-etl")
SUBNETS = os.environ.get(
    "ECS_SUBNETS",
    "subnet-0685a1cd4c6dbea34,subnet-04096d910b56372fd,subnet-0b515ac89b9fbf99b",
).split(",")
SECURITY_GROUPS = os.environ.get(
    "ECS_SECURITY_GROUPS", "sg-0420f49957d8f8159"
).split(",")
CONTAINER_NAME = os.environ.get("ECS_CONTAINER_NAME", "etl")

ecs = boto3.client("ecs", region_name=REGION)

# Marker key shape: raw/tv/_DONE_2026-05-03.txt
_DONE_RE = re.compile(r"_DONE_(\d{4}-\d{2}-\d{2})\.txt$")


def handler(event, context):
    launched = []
    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name")
        key = unquote_plus(s3.get("object", {}).get("key", ""))

        m = _DONE_RE.search(key)
        if not m:
            logger.info("Ignoring object that does not match _DONE_ pattern: s3://%s/%s", bucket, key)
            continue
        ingestion_date = m.group(1)

        logger.info(
            "Marker received: s3://%s/%s ingestion_date=%s -> launching ECS RunTask",
            bucket, key, ingestion_date,
        )

        resp = ecs.run_task(
            cluster=CLUSTER,
            taskDefinition=TASK_DEFINITION,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": SUBNETS,
                    "securityGroups": SECURITY_GROUPS,
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": CONTAINER_NAME,
                        "environment": [
                            {"name": "USE_VPS_RAW", "value": "true"},
                            {"name": "INGESTION_DATE", "value": ingestion_date},
                        ],
                    }
                ]
            },
        )

        task_arns = [t["taskArn"] for t in resp.get("tasks", [])]
        failures = resp.get("failures", [])
        logger.info("RunTask: tasks=%s failures=%s", task_arns, failures)
        launched.append({"ingestion_date": ingestion_date, "tasks": task_arns, "failures": failures})

    return {"statusCode": 200, "body": json.dumps({"launched": launched})}
