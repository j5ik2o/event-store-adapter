package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	awsdb "github.com/aws/aws-sdk-go-v2/service/dynamodb"
	es "github.com/j5ik2o/event-store-adapter-go/v2"
	"github.com/j5ik2o/event-store-adapter-go/v2/dynamodb"
)

type ID struct { TypeName string `json:"type_name"`; Value string `json:"value"` }
type Config struct { Endpoint, Journal, Snapshot, Head string; HistoryIndex string `json:"history_index"`; RetentionCount int `json:"retention_count"` }
type Event struct { ID; SeqNr es.SeqNr `json:"seq_nr"`; OccurredAt string `json:"occurred_at_ns"`; Manifest string `json:"manifest"`; Payload json.RawMessage `json:"payload"` }
type Snapshot struct { SeqNr es.SeqNr `json:"seq_nr"`; Manifest string `json:"manifest"`; Aggregate json.RawMessage `json:"aggregate"` }
type Request struct { Op string; Config Config; Event Event; Snapshot Snapshot; ID ID; SeqNr es.SeqNr `json:"seq_nr"` }

func aggregateID(value ID) (es.AggregateID, error) { return es.NewAggregateID(value.TypeName, value.Value) }
func envelope(value Event) (es.EventEnvelope[json.RawMessage], error) {
	id, err := aggregateID(value.ID)
	if err != nil { return es.EventEnvelope[json.RawMessage]{}, err }
	nanos, err := strconv.ParseInt(value.OccurredAt, 10, 64)
	if err != nil { return es.EventEnvelope[json.RawMessage]{}, err }
	return es.NewEventEnvelope(id, value.SeqNr, time.Unix(0, nanos).UTC(), value.Payload, es.WithManifest(value.Manifest))
}

func main() {
	ctx := context.Background()
	var store es.EventStore[json.RawMessage, json.RawMessage]
	input := bufio.NewScanner(os.Stdin)
	input.Buffer(make([]byte, 4096), 4*1024*1024)
	output := json.NewEncoder(os.Stdout)
	for input.Scan() {
		var request Request
		if err := json.Unmarshal(input.Bytes(), &request); err != nil { panic(err) }
		result, err := operate(ctx, &store, request)
		reply := map[string]any{"status": "ok", "result": result}
		if err != nil {
			kind, classified := es.KindOf(err)
			if !classified { panic(err) }
			categories := map[es.Kind]string{es.KindOptimisticLock: "optimisticLock", es.KindContractViolation: "contractViolation", es.KindSerialization: "serialization", es.KindConfiguration: "configuration", es.KindStorage: "storage"}
			reply = map[string]any{"status": "error", "category": categories[kind], "message": err.Error(), "error_type": fmt.Sprintf("%T", err)}
		}
		if err := output.Encode(reply); err != nil { panic(err) }
	}
	if err := input.Err(); err != nil { panic(err) }
}

func operate(ctx context.Context, store *es.EventStore[json.RawMessage, json.RawMessage], r Request) (any, error) {
	switch r.Op {
	case "create":
		client := awsdb.NewFromConfig(aws.Config{Region: "us-east-1", Credentials: credentials.NewStaticCredentialsProvider("local", "local", "")}, func(o *awsdb.Options) { o.BaseEndpoint = &r.Config.Endpoint })
		retention, err := es.KeepLatest(r.Config.RetentionCount)
		if err != nil { return nil, err }
		*store, err = dynamodb.New(ctx, client, dynamodb.Config{JournalTableName:r.Config.Journal, SnapshotTableName:r.Config.Snapshot, HeadTableName:r.Config.Head, SnapshotHistoryIndexName:r.Config.HistoryIndex}, es.NewJSONSerializer[json.RawMessage](), es.NewJSONSerializer[json.RawMessage](), es.WithRetentionCount(retention))
		return nil, err
	case "persistEvent", "persistEventAndSnapshot":
		event, err := envelope(r.Event)
		if err != nil { return nil, err }
		if r.Op == "persistEvent" { return nil, (*store).PersistEvent(ctx, event) }
		snapshot, err := es.NewSnapshotEnvelope(r.Snapshot.Aggregate, r.Snapshot.SeqNr, es.WithManifest(r.Snapshot.Manifest))
		if err != nil { return nil, err }
		return nil, (*store).PersistEventAndSnapshot(ctx, event, snapshot)
	case "getEvents":
		id, err := aggregateID(r.ID)
		if err != nil { return nil, err }
		events, err := (*store).GetEventsByIDSinceSeqNr(ctx, id, r.SeqNr)
		if err != nil { return nil, err }
		observed := make([]any, 0, len(events))
		for _, event := range events { observed = append(observed, map[string]any{"aid":event.AggregateID(), "seq_nr":event.SeqNr(), "occurred_at_ns":strconv.FormatInt(event.OccurredAt().UnixNano(),10), "manifest":event.Manifest(), "payload":event.Payload()}) }
		return observed, nil
	case "getLatestSnapshot":
		id, err := aggregateID(r.ID)
		if err != nil { return nil, err }
		latest, err := (*store).GetLatestSnapshotByID(ctx, id)
		if err != nil || latest == nil { return nil, err }
		var snapshot any
		if latest.Snapshot != nil { snapshot = map[string]any{"seq_nr":latest.Snapshot.SeqNr(), "manifest":latest.Snapshot.Manifest(), "aggregate":latest.Snapshot.Aggregate()} }
		return map[string]any{"head_seq_nr":latest.HeadSeqNr, "snapshot":snapshot}, nil
	default: return nil, fmt.Errorf("unknown operation")
	}
}
