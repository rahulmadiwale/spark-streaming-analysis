import sys
import requests

from pyspark import SparkConf, SparkContext
from pyspark.streaming import StreamingContext
from pyspark.sql import Row,SQLContext

# Create Spark Configuration
conf = SparkConf()
conf.setAppName("TwitterStreamApp")

# Create Spark instance with the above config
sc = SparkContext(conf=conf)
sc.setLogLevel("ERROR")

# Create Spark Streaming Context with interval: 2 seconds
ssc = StreamingContext(sc, 2)
# setting a checkpoint to allow RDD recovery
ssc.checkpoint("checkpoint_TwitterApp")
# read data from port 9009
dataStream = ssc.socketTextStream("localhost",9009)


def aggregate_tags_count(new_values, running_total):
    if running_total is None: running_total = 0
    return sum(new_values, running_total)


def get_sql_context_instance(spark_context):
    if ('sqlContextSingletonInstance' not in globals()):
        globals()['sqlContextSingletonInstance'] = SQLContext(spark_context)
    return globals()['sqlContextSingletonInstance']


def send_df_to_dashboard(df):
    # Extract hashtags from DF
    top_tags = [str(t.hashtag) for t in df.select("hashtag").collect()]
    # Extract counts from DF
    tags_count = [p.hashtag_count for p in df.select("hashtag_count").collect()]
    # Initialize and send the data through REST API
    url = 'http://localhost:5001/updateData'
    request_data = {'label': str(top_tags), 'data': str(tags_count)}
    response = requests.post(url, data=request_data)


def process_rdd(time, rdd):
    print("----------- %s -----------" % str(time))
    try:
        # Get spark sql singleton context from the current context
        sql_context = get_sql_context_instance(rdd.context)
        # convert the RDD to Row RDD
        row_rdd = rdd.map(lambda w: Row(hashtag=w[0], hashtag_count=w[1]))
        # create a DF from the Row RDD
        hashtags_df = sql_context.createDataFrame(row_rdd)
        # Register the dataframe as table
        hashtags_df.registerTempTable("hashtags")
        # get the top 10 hashtags from the table using SQL and print them
        hashtag_counts_df = sql_context.sql("select hashtag, hashtag_count from hashtags order by hashtag_count desc limit 10")
        hashtag_counts_df.show()
        # call this method to prepare top 10 hashtags DF and send them
        send_df_to_dashboard(hashtag_counts_df)
    except:
        e = sys.exc_info()[0]
        print("Error: %s" % e)


words = dataStream.flatMap(lambda line: line.split(" "))
hashtags = words.filter(lambda w: '#' in w).map(lambda x: (x, 1))
tags_totals = hashtags.updateStateByKey(aggregate_tags_count)
tags_totals.foreachRDD(process_rdd)

# Start streaming computation
ssc.start()
# Wait streaming to finish
ssc.awaitTermination()



