# Detailed GCP architecture diagram using graphviz

from graphviz import Digraph

g = Digraph(format="png")
g.attr(rankdir="LR", size="12,8")

# Public Layer
g.node("Users", "End Users / Applications", shape="oval")

# GCP Boundary
with g.subgraph(name="cluster_gcp") as c:
    c.attr(label="Google Cloud Platform", style="rounded")

    c.node("LB", "Cloud Load Balancer")

    with c.subgraph(name="cluster_vpc") as v:
        v.attr(label="VPC Network", style="rounded")

        v.node("SQL", "Cloud SQL\n(Transactional DB)", shape="cylinder")
        v.node("GCS", "Cloud Storage\n(Raw Files / Backups)", shape="folder")
        v.node("BQ", "BigQuery\n(Data Warehouse)", shape="cylinder")
        v.node("BI", "Looker Studio\n(Dashboards)", shape="box")

    # Security & Ops
    c.node("IAM", "IAM")
    c.node("KMS", "Cloud KMS")
    c.node("MON", "Monitoring & Logging")

# Flow
g.edges([
    ("Users", "LB"),
    ("LB", "SQL"),
    ("SQL", "GCS"),
    ("GCS", "BQ"),
    ("BQ", "BI")
])

# Security links
g.edges([
    ("IAM", "SQL"),
    ("IAM", "GCS"),
    ("IAM", "BQ"),
    ("KMS", "SQL"),
    ("KMS", "GCS"),
    ("MON", "SQL"),
    ("MON", "BQ")
])

g.render("gcp_architecture_diagram")
