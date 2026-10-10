package interop;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.j5ik2o.event.store.adapter.java.core.*;
import com.github.j5ik2o.event.store.adapter.java.dynamodb.DynamoDbTableConfig;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;

/** 入出力と公開値型の変換だけを共有し、保存先の操作は各言語に任せる。 */
public final class Wire {
  public static final ObjectMapper JSON = new ObjectMapper();
  public interface Handler { Object apply(JsonNode request) throws Exception; }

  public static void run(Handler handler, Runnable close) throws Exception {
    try (BufferedReader input = new BufferedReader(new InputStreamReader(System.in))) {
      String line;
      while ((line = input.readLine()) != null) {
        Map<String, Object> reply = new LinkedHashMap<>();
        try {
          Object result = handler.apply(JSON.readTree(line));
          reply.put("status", "ok");
          reply.put("result", result);
        } catch (EventStoreException error) {
          reply.put("status", "error");
          reply.put("category", category(error.category()));
          reply.put("message", error.getMessage());
          reply.put("error_type", error.getClass().getName());
        }
        System.out.println(JSON.writeValueAsString(reply));
        System.out.flush();
      }
    } finally { close.run(); }
  }

  private static String category(ErrorCategory value) {
    switch (value) {
      case OPTIMISTIC_LOCK: return "optimisticLock";
      case CONTRACT_VIOLATION: return "contractViolation";
      case SERIALIZATION: return "serialization";
      case CONFIGURATION: return "configuration";
      case STORAGE: return "storage";
      default: throw new IllegalArgumentException(value.name());
    }
  }

  public static DynamoDbClient client(JsonNode config) {
    return DynamoDbClient.builder().endpointOverride(URI.create(config.get("endpoint").asText()))
        .region(Region.US_EAST_1)
        .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("local", "local")))
        .httpClientBuilder(UrlConnectionHttpClient.builder()).build();
  }

  public static DynamoDbTableConfig tables(JsonNode config) {
    return DynamoDbTableConfig.builder().journalTableName(config.get("journal").asText())
        .snapshotTableName(config.get("snapshot").asText()).headTableName(config.get("head").asText())
        .snapshotAidIndexName(config.get("history_index").asText())
        .retentionPolicy(RetentionPolicy.delete(config.get("retention_count").asInt())).build();
  }

  public static EventStoreConfig<JsonNode, JsonNode> serializers() {
    PayloadSerializer<JsonNode> serializer = JsonPayloadSerializer.of(JSON, JsonNode.class);
    return EventStoreConfig.<JsonNode, JsonNode>builder()
        .payloadSerializer(serializer).snapshotSerializer(serializer).build();
  }

  public static AggregateId id(JsonNode input) {
    return AggregateId.of(input.get("type_name").asText(), input.get("value").asText());
  }

  public static EventEnvelope<JsonNode> event(JsonNode input) {
    long nanos = Long.parseLong(input.get("occurred_at_ns").asText());
    return EventEnvelope.<JsonNode>builder().aggregateId(id(input))
        .seqNr(input.get("seq_nr").asLong())
        .occurredAt(Instant.ofEpochSecond(Math.floorDiv(nanos, 1_000_000_000L), Math.floorMod(nanos, 1_000_000_000L)))
        .manifest(input.get("manifest").asText()).payload(input.get("payload")).build();
  }

  public static SnapshotEnvelope<JsonNode> snapshot(JsonNode input) {
    return SnapshotEnvelope.<JsonNode>builder().seqNr(input.get("seq_nr").asLong())
        .manifest(input.get("manifest").asText()).aggregate(input.get("aggregate")).build();
  }

  public static Map<String, Object> observedEvent(EventEnvelope<JsonNode> event) {
    Instant time = event.occurredAt();
    long nanos = Math.addExact(Math.multiplyExact(time.getEpochSecond(), 1_000_000_000L), time.getNano());
    return Map.of("aid", event.aggregateId().asString(), "seq_nr", event.seqNr(),
        "occurred_at_ns", Long.toString(nanos), "manifest", event.manifest(), "payload", event.payload());
  }

  public static Map<String, Object> latest(SnapshotEnvelope<JsonNode> snapshot, long head) {
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("head_seq_nr", head);
    result.put("snapshot", snapshot == null ? null : Map.of("seq_nr", snapshot.seqNr(),
        "manifest", snapshot.manifest(), "aggregate", snapshot.aggregate()));
    return result;
  }
}
