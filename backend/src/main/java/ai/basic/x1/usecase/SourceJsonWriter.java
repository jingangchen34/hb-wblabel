package ai.basic.x1.usecase;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.util.DefaultIndenter;
import com.fasterxml.jackson.core.util.DefaultPrettyPrinter;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;

import java.io.IOException;
import java.nio.file.Path;

/** Keeps regenerated metadata visually and numerically aligned with the imported JSON files. */
final class SourceJsonWriter {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
            .setNodeFactory(JsonNodeFactory.withExactBigDecimals(true));
    private static final DefaultPrettyPrinter FORMAT = new SourcePrettyPrinter();

    private SourceJsonWriter() {
    }

    static ObjectMapper mapper() {
        return MAPPER;
    }

    static void write(Path destination, JsonNode value) throws IOException {
        MAPPER.writer(FORMAT).writeValue(destination.toFile(), value);
    }

    private static final class SourcePrettyPrinter extends DefaultPrettyPrinter {
        private SourcePrettyPrinter() {
            var indenter = new DefaultIndenter("    ", "\n");
            indentObjectsWith(indenter);
            indentArraysWith(indenter);
        }

        private SourcePrettyPrinter(SourcePrettyPrinter base) {
            super(base);
        }

        @Override
        public DefaultPrettyPrinter createInstance() {
            return new SourcePrettyPrinter(this);
        }

        @Override
        public void writeObjectFieldValueSeparator(JsonGenerator generator) throws IOException {
            generator.writeRaw(": ");
        }
    }
}
