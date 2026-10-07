Storefront's shop-catalog and shop-checkout store their data in MongoDB Atlas.
Their traces carry a child span for every database call (`db.system = mongodb`,
`db.mongodb.collection`, and the command in `db.statement`). Atlas sends its own cluster metrics to Bronto,
which you can read with list_atlas_metrics and query_atlas_metrics. Atlas slow-query
log lines are in Bronto too, searchable like any other log.
The MongoDB log is the atlas-mongod dataset in the mongodb-dublin collection: search it too.
