package interop

import com.fasterxml.jackson.databind.JsonNode
import com.github.j5ik2o.event.store.adapter.scala.EventStore
import software.amazon.awssdk.services.dynamodb.DynamoDbClient
import scala.jdk.CollectionConverters._

object ScalaDriver {
  def main(args: Array[String]): Unit = {
    var client: DynamoDbClient = null
    var store: EventStore[JsonNode, JsonNode] = null
    Wire.run(request => {
      request.get("op").asText() match {
        case "create" =>
          if (client != null) client.close()
          client = Wire.client(request.get("config"))
          store = EventStore.ofDynamoDB(client, Wire.tables(request.get("config")), Wire.serializers()).get
          null
        case "persistEvent" =>
          store.persistEvent(Wire.event(request.get("event"))).get
          null
        case "persistEventAndSnapshot" =>
          store.persistEventAndSnapshot(Wire.event(request.get("event")), Wire.snapshot(request.get("snapshot"))).get
          null
        case "getEvents" =>
          store.getEventsByIdSinceSeqNr(Wire.id(request.get("id")), request.get("seq_nr").asLong())
            .get.map(Wire.observedEvent).asJava
        case "getLatestSnapshot" =>
          store.getLatestSnapshotById(Wire.id(request.get("id"))).get
            .map(value => Wire.latest(value.snapshot.orNull, value.headSeqNr)).orNull
        case _ => throw new IllegalArgumentException("unknown operation")
      }
    }, () => if (client != null) client.close())
  }
}
