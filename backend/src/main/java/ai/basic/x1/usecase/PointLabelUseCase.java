package ai.basic.x1.usecase;

import ai.basic.x1.adapter.dto.request.PointLabelSaveDTO;
import org.springframework.beans.factory.annotation.Value;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class PointLabelUseCase {

    @Value("${occ.annotation.path:./data/occ-annotations}")
    private String annotationPath;

    public byte[] getLabels(Long dataId) throws IOException {
        var path = labelPath(dataId);
        if (!Files.exists(path)) {
            return new byte[0];
        }
        return Files.readAllBytes(path);
    }

    public void saveLabels(PointLabelSaveDTO saveDTO) throws IOException {
        Files.createDirectories(root());
        var labels = Base64.getDecoder().decode(saveDTO.getLabelsBase64());
        Files.write(labelPath(saveDTO.getDataId()), labels);
    }

    public Path exportClip(Long sceneId) throws IOException {
        Files.createDirectories(root());
        var exportPath = root().resolve("scene-" + sceneId + "-point-labels.zip");
        try (var output = new ZipOutputStream(Files.newOutputStream(exportPath))) {
            try (var stream = Files.list(root())) {
                var files = stream.filter(path -> path.getFileName().toString().endsWith(".label")).collect(Collectors.toList());
                for (var path : files) {
                    output.putNextEntry(new ZipEntry(path.getFileName().toString()));
                    Files.copy(path, output);
                    output.closeEntry();
                }
            }
        }
        return exportPath;
    }

    private Path root() {
        return Path.of(annotationPath);
    }

    private Path labelPath(Long dataId) {
        return root().resolve(dataId + ".label");
    }
}

