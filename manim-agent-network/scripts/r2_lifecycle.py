"""Set a TTL lifecycle rule on the R2 bucket so rendered videos under jobs/ expire
(R2 free tier is 10 GB). Run once after the bucket exists:

    R2_ACCOUNT_ID=... R2_BUCKET=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
      python scripts/r2_lifecycle.py [days]

Idempotent: re-running just overwrites the rule.
"""
import os
import sys


def set_lifecycle(days: int = 30):
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    s3.put_bucket_lifecycle_configuration(
        Bucket=os.environ["R2_BUCKET"],
        LifecycleConfiguration={"Rules": [{
            "ID": "expire-job-artifacts",
            "Status": "Enabled",
            "Filter": {"Prefix": "jobs/"},
            "Expiration": {"Days": days},
        }]},
    )
    print(f"R2 lifecycle set: jobs/* expires after {days} days")


if __name__ == "__main__":
    set_lifecycle(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
