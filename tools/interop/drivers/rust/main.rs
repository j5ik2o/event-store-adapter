use std::io::{self, BufRead, Write};
use aws_sdk_dynamodb::{config::{BehaviorVersion, Credentials, Region}, Client};
use chrono::{DateTime, Utc};
use event_store_adapter_rs::{AggregateId, AidString, DynamoDbOptions, DynamoDbTables, EventEnvelope, EventStoreError, EventStoreForDynamoDB, RetentionSettings, SnapshotEnvelope};
use serde_json::{json, Value};

#[derive(Debug, Clone)]
struct Id { type_name: String, value: String }
impl AggregateId for Id {
    fn type_name(&self) -> String { self.type_name.clone() }
    fn value(&self) -> String { self.value.clone() }
}
type Store = EventStoreForDynamoDB<Id, Value, Value>;
fn id(input: &Value) -> Id { Id { type_name: input["type_name"].as_str().unwrap().into(), value: input["value"].as_str().unwrap().into() } }
fn event(input: &Value) -> EventEnvelope<Id, Value> {
    let nanos: i64 = input["occurred_at_ns"].as_str().unwrap().parse().unwrap();
    let time: DateTime<Utc> = DateTime::from_timestamp(nanos.div_euclid(1_000_000_000), nanos.rem_euclid(1_000_000_000) as u32).unwrap();
    EventEnvelope::new(id(input), input["seq_nr"].as_u64().unwrap(), time, input["payload"].clone())
        .with_manifest(input["manifest"].as_str().unwrap())
}
fn observed(event: EventEnvelope<Id, Value>) -> Value {
    json!({"aid":AidString::from_aggregate_id(event.aggregate_id()).unwrap().as_str(), "seq_nr":event.seq_nr(),
        "occurred_at_ns":event.occurred_at().timestamp_nanos_opt().unwrap().to_string(), "manifest":event.manifest(), "payload":event.payload()})
}

#[tokio::main]
async fn main() {
    let mut store: Option<Store> = None;
    for line in io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        let reply = match operate(&mut store, &request).await {
            Ok(result) => json!({"status":"ok", "result":result}),
            Err(error) => {
                let category = match &error {
                    EventStoreError::OptimisticLock { .. } => "optimisticLock",
                    EventStoreError::ContractViolation { .. } => "contractViolation",
                    EventStoreError::Serialization { .. } => "serialization",
                    EventStoreError::Configuration { .. } => "configuration",
                    EventStoreError::Storage { .. } => "storage",
                    _ => panic!("unclassified library error: {error:?}"),
                };
                json!({"status":"error", "category":category, "message":error.to_string(), "error_type":format!("{error:?}")})
            }
        };
        println!("{reply}");
        io::stdout().flush().unwrap();
    }
}

async fn operate(store: &mut Option<Store>, request: &Value) -> Result<Value, EventStoreError> {
    if request["op"] == "create" {
        let c = &request["config"];
        let client = Client::from_conf(aws_sdk_dynamodb::Config::builder()
            .behavior_version(BehaviorVersion::latest()).region(Region::new("us-east-1"))
            .sleep_impl(aws_smithy_async::rt::sleep::TokioSleep::new())
            .credentials_provider(Credentials::new("local", "local", None, None, "interop"))
            .endpoint_url(c["endpoint"].as_str().unwrap()).build());
        let tables = DynamoDbTables { journal_table_name:c["journal"].as_str().unwrap().into(),
            snapshot_table_name:c["snapshot"].as_str().unwrap().into(), head_table_name:c["head"].as_str().unwrap().into(),
            snapshot_history_index_name:c["history_index"].as_str().unwrap().into() };
        let options = DynamoDbOptions { retention:RetentionSettings::keep_latest(c["retention_count"].as_u64().unwrap() as usize), ..Default::default() };
        *store = Some(Store::open(client, tables, options).await?);
        return Ok(Value::Null);
    }
    let store = store.as_ref().unwrap();
    match request["op"].as_str().unwrap() {
        "persistEvent" => { store.persist_event(event(&request["event"])).await?; Ok(Value::Null) }
        "persistEventAndSnapshot" => {
            let input = &request["snapshot"];
            store.persist_event_and_snapshot(event(&request["event"]), SnapshotEnvelope::new(input["aggregate"].clone(), input["seq_nr"].as_u64().unwrap()).with_manifest(input["manifest"].as_str().unwrap())).await?;
            Ok(Value::Null)
        }
        "getEvents" => Ok(Value::Array(store.get_events_by_id_since_seq_nr(&id(&request["id"]), request["seq_nr"].as_u64().unwrap()).await?.into_iter().map(observed).collect())),
        "getLatestSnapshot" => Ok(store.get_latest_snapshot_by_id(&id(&request["id"])).await?.map(|latest| json!({
            "head_seq_nr":latest.head_seq_nr(), "snapshot":latest.snapshot().map(|s| json!({"seq_nr":s.seq_nr(), "manifest":s.manifest(), "aggregate":s.aggregate()})),
        })).unwrap_or(Value::Null)),
        _ => panic!("unknown operation"),
    }
}
