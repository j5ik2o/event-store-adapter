import { createRequire } from 'node:module';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const require = createRequire(pathToFileURL(`${process.env.INTEROP_JS_LIBRARY}/package.json`));
const { AggregateId, EventEnvelope, SnapshotEnvelope, EventStore } = require(process.env.INTEROP_JS_LIBRARY);
const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const unwrap = result => { if (result.type === 'err') throw result.error; return result.value; };
const id = input => unwrap(AggregateId.of(input.type_name, input.value));
const event = input => unwrap(EventEnvelope.create({
  aggregateId: id(input), seqNr: input.seq_nr,
  occurredAt: new Date(Number(BigInt(input.occurred_at_ns) / 1_000_000n)),
  manifest: input.manifest, payload: input.payload,
}));
const observedEvent = value => ({
  aid: unwrap(AggregateId.asString(value.aggregateId)), seq_nr: value.seqNr,
  occurred_at_ns: (BigInt(value.occurredAt.getTime()) * 1_000_000n).toString(),
  manifest: value.manifest, payload: value.payload,
});
const categories = {
  'optimistic-lock-conflict': 'optimisticLock', 'contract-violation': 'contractViolation',
  'serialization-error': 'serialization', 'configuration-error': 'configuration', 'storage-error': 'storage',
};
let client, store;
try {
  for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
    const request = JSON.parse(line);
    let reply;
    try {
      let result = null;
      switch (request.op) {
        case 'create': {
          client?.destroy();
          const config = request.config;
          client = new DynamoDBClient({ endpoint: config.endpoint, region: 'us-east-1', credentials: { accessKeyId: 'local', secretAccessKey: 'local' } });
          store = unwrap(await EventStore.createDynamoDB({ client,
            tables: { journal: config.journal, snapshot: config.snapshot, head: config.head },
            snapshotAidIndexName: config.history_index, retention: { count: config.retention_count },
          }));
          break;
        }
        case 'persistEvent': unwrap(await store.persistEvent(event(request.event))); break;
        case 'persistEventAndSnapshot':
          unwrap(await store.persistEventAndSnapshot(event(request.event), unwrap(SnapshotEnvelope.create({
            seqNr: request.snapshot.seq_nr, manifest: request.snapshot.manifest, aggregate: request.snapshot.aggregate,
          })))); break;
        case 'getEvents':
          result = unwrap(await store.getEventsByIdSinceSeqNr(id(request.id), request.seq_nr)).map(observedEvent); break;
        case 'getLatestSnapshot': {
          const value = unwrap(await store.getLatestSnapshotById(id(request.id)));
          result = value === undefined ? null : { head_seq_nr: value.headSeqNr, snapshot: value.snapshot === undefined ? null : {
            seq_nr: value.snapshot.seqNr, manifest: value.snapshot.manifest, aggregate: value.snapshot.aggregate,
          }}; break;
        }
        default: throw new Error('unknown operation');
      }
      reply = { status: 'ok', result };
    } catch (error) {
      if (!categories[error.type]) throw error;
      reply = { status: 'error', category: categories[error.type], error_type: error.type, message: error.message };
    }
    process.stdout.write(`${JSON.stringify(reply)}\n`);
  }
} finally { client?.destroy(); }
