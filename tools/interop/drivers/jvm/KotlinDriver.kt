package interop

import com.fasterxml.jackson.databind.JsonNode
import com.github.j5ik2o.event.store.adapter.kotlin.EventStore
import software.amazon.awssdk.services.dynamodb.DynamoDbClient

fun main() {
    var client: DynamoDbClient? = null
    lateinit var store: EventStore<JsonNode, JsonNode>
    Wire.run({ request ->
        when (request["op"].asText()) {
            "create" -> {
                client?.close()
                client = Wire.client(request["config"])
                store = EventStore.ofDynamoDB(client!!, Wire.tables(request["config"]), Wire.serializers())
                null
            }
            "persistEvent" -> { store.persistEvent(Wire.event(request["event"])); null }
            "persistEventAndSnapshot" -> {
                store.persistEventAndSnapshot(Wire.event(request["event"]), Wire.snapshot(request["snapshot"]))
                null
            }
            "getEvents" -> store.getEventsByIdSinceSeqNr(Wire.id(request["id"]), request["seq_nr"].asLong())
                .map(Wire::observedEvent)
            "getLatestSnapshot" -> store.getLatestSnapshotById(Wire.id(request["id"]))?.let {
                Wire.latest(it.snapshot().orElse(null), it.headSeqNr())
            }
            else -> error("unknown operation")
        }
    }, { client?.close() })
}
