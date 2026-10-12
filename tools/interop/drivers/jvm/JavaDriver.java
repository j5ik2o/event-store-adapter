package interop;

import com.fasterxml.jackson.databind.JsonNode;
import com.github.j5ik2o.event.store.adapter.java.core.EventStore;
import com.github.j5ik2o.event.store.adapter.java.core.SnapshotReadResult;
import com.github.j5ik2o.event.store.adapter.java.dynamodb.DynamoDbEventStore;
import java.util.stream.Collectors;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;

public final class JavaDriver {
  private static DynamoDbClient client;
  private static EventStore<JsonNode, JsonNode> store;

  public static void main(String[] args) throws Exception {
    Wire.run(request -> {
      switch (request.get("op").asText()) {
        case "create":
          if (client != null) client.close();
          client = Wire.client(request.get("config"));
          store = DynamoDbEventStore.create(client, Wire.tables(request.get("config")), Wire.serializers());
          return null;
        case "persistEvent":
          store.persistEvent(Wire.event(request.get("event")));
          return null;
        case "persistEventAndSnapshot":
          store.persistEventAndSnapshot(Wire.event(request.get("event")), Wire.snapshot(request.get("snapshot")));
          return null;
        case "getEvents":
          return store.getEventsByIdSinceSeqNr(Wire.id(request.get("id")), request.get("seq_nr").asLong())
              .stream().map(Wire::observedEvent).collect(Collectors.toList());
        case "getLatestSnapshot":
          SnapshotReadResult<JsonNode> latest = store.getLatestSnapshotById(Wire.id(request.get("id"))).orElse(null);
          return latest == null ? null : Wire.latest(latest.snapshot().orElse(null), latest.headSeqNr());
        default: throw new IllegalArgumentException("unknown operation");
      }
    }, () -> { if (client != null) client.close(); });
  }
}
