package ai.basic.x1.usecase;

import ai.basic.x1.adapter.api.context.RequestContextHolder;
import ai.basic.x1.adapter.dto.request.PointLabelPatchDTO;
import ai.basic.x1.adapter.dto.request.PointLabelSaveDTO;
import ai.basic.x1.adapter.port.dao.DataInfoDAO;
import ai.basic.x1.adapter.port.minio.MinioProp;
import ai.basic.x1.adapter.port.minio.MinioService;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataInfo;
import ai.basic.x1.entity.FileBO;
import cn.hutool.core.collection.CollectionUtil;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.stream.Collectors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

@Slf4j
public class PointLabelUseCase {

    @Value("${occ.annotation.path:./data/occ-annotations}")
    private String annotationPath;

    @Autowired
    private DataInfoDAO dataInfoDAO;

    @Autowired
    private FileUseCase fileUseCase;

    @Autowired
    private MinioService minioService;

    @Autowired
    private MinioProp minioProp;

    public byte[] getLabels(Long dataId) throws IOException {
        var path = labelPath(dataId);
        if (!Files.exists(path)) {
            return new byte[0];
        }
        return Files.readAllBytes(path);
    }

    public byte[] getPreAnnotationLabels(Long preAnnotationId, Long dataId) throws IOException {
        var path = preAnnotationLabelPath(preAnnotationId, dataId);
        return Files.exists(path) ? Files.readAllBytes(path) : new byte[0];
    }

    public void saveLabels(PointLabelSaveDTO saveDTO) throws IOException {
        var preAnnotationId = saveDTO.getPreAnnotationId();
        var path = preAnnotationId == null
                ? labelPath(saveDTO.getDataId())
                : preAnnotationLabelPath(preAnnotationId, saveDTO.getDataId());
        Files.createDirectories(path.getParent());
        var labels = Base64.getDecoder().decode(saveDTO.getLabelsBase64());
        Files.write(path, labels);
        if (preAnnotationId == null) syncLabelResourceQuietly(saveDTO.getDataId(), labels);
    }

    public void patchLabels(PointLabelPatchDTO patchDTO) throws IOException {
        Files.createDirectories(root());
        var indices = patchDTO.getIndices();
        if (indices == null || indices.isEmpty()) {
            return;
        }

        var patchLabels = Base64.getDecoder().decode(patchDTO.getLabelsBase64());
        if (patchLabels.length != indices.size()) {
            throw new IOException("Label patch size does not match indices size");
        }

        var path = labelPath(patchDTO.getDataId());
        byte[] labels;
        if (Files.exists(path)) {
            labels = Files.readAllBytes(path);
        } else {
            labels = new byte[Math.max(0, patchDTO.getPointCount() == null ? 0 : patchDTO.getPointCount())];
        }

        var requiredLength = labels.length;
        for (var index : indices) {
            if (index != null && index >= 0) {
                requiredLength = Math.max(requiredLength, index + 1);
            }
        }
        if (requiredLength > labels.length) {
            labels = Arrays.copyOf(labels, requiredLength);
        }

        for (var i = 0; i < indices.size(); i++) {
            var index = indices.get(i);
            if (index != null && index >= 0 && index < labels.length) {
                labels[index] = patchLabels[i];
            }
        }
        Files.write(path, labels);
        syncLabelResourceQuietly(patchDTO.getDataId(), labels);
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

    private Path preAnnotationLabelPath(Long preAnnotationId, Long dataId) throws IOException {
        if (preAnnotationId == null || preAnnotationId <= 0 || dataId == null || dataId <= 0) {
            throw new IOException("Invalid pre-annotation or data id");
        }
        return root().resolve("preannotation-" + preAnnotationId).resolve(dataId + ".label");
    }

    public void syncExternalLabelResource(Long dataId, String relativePath, long size, Long userId) {
        var normalized = Path.of(relativePath == null ? "" : relativePath).normalize();
        if (normalized.isAbsolute() || normalized.startsWith("..") || !normalized.toString().endsWith(".label")) {
            throw new IllegalArgumentException("Invalid external OCC label path: " + relativePath);
        }
        var files = fileUseCase.saveBatchFile(userId, List.of(FileBO.builder()
                .name(normalized.getFileName().toString())
                .originalName(normalized.getFileName().toString())
                .path(normalized.toString().replace('\\', '/'))
                .type("application/octet-stream")
                .size(size)
                .bucketName("external-data")
                .build()));
        if (CollectionUtil.isEmpty(files)) return;
        attachLabelResource(dataId, files.get(0).getId(), normalized.getFileName().toString());
    }

    private void attachLabelResource(Long dataId, Long fileId, String name) {
        var dataInfo = dataInfoDAO.getById(dataId);
        if (dataInfo == null) return;
        var content = normalizeContent(dataInfo.getContent());
        content.removeIf(node -> "occ_label".equalsIgnoreCase(node.getName()));
        content.add(DataInfo.FileNode.builder()
                .name("occ_label").type("directory")
                .files(List.of(DataInfo.FileNode.builder()
                        .name(name).type("file").fileId(fileId).build()))
                .build());
        dataInfoDAO.updateById(DataInfo.builder().id(dataId).content(content).build());
    }

    private void syncLabelResourceQuietly(Long dataId, byte[] labels) {
        try {
            syncLabelResource(dataId, labels);
        } catch (Exception exception) {
            log.warn("Sync point label resource failed, dataId={}, labelBytes={}", dataId, labels.length, exception);
        }
    }

    private void syncLabelResource(Long dataId, byte[] labels) throws IOException {
        var dataInfo = dataInfoDAO.getById(dataId);
        if (dataInfo == null) return;

        var objectName = "occ-annotations/" + dataId + ".label";
        try (var input = new ByteArrayInputStream(labels)) {
            minioService.uploadFileWithoutUrl(
                    minioProp.getBucketName(),
                    objectName,
                    input,
                    "application/octet-stream",
                    labels.length
            );
        } catch (Exception exception) {
            throw new IOException("Upload point label resource failed", exception);
        }

        var userId = dataInfo.getCreatedBy();
        var context = RequestContextHolder.getContext();
        if (context != null && context.getUserInfo() != null && context.getUserInfo().getId() != null) {
            userId = context.getUserInfo().getId();
        }

        var files = fileUseCase.saveBatchFile(userId, List.of(FileBO.builder()
                .name(dataId + ".label")
                .originalName(dataId + ".label")
                .path(objectName)
                .type("application/octet-stream")
                .size((long) labels.length)
                .bucketName(minioProp.getBucketName())
                .build()));
        if (CollectionUtil.isEmpty(files)) return;

        var fileId = files.get(0).getId();
        attachLabelResource(dataId, fileId, dataId + ".label");
        log.info("Synced point label resource, dataId={}, fileId={}, labelBytes={}", dataId, fileId, labels.length);
    }

    @SuppressWarnings("unchecked")
    private List<DataInfo.FileNode> normalizeContent(List<DataInfo.FileNode> rawContent) {
        var content = new ArrayList<DataInfo.FileNode>();
        if (rawContent == null) {
            return content;
        }
        for (Object rawNode : (List<?>) rawContent) {
            var node = toFileNode(rawNode);
            if (node != null) {
                content.add(node);
            }
        }
        return content;
    }

    @SuppressWarnings("unchecked")
    private DataInfo.FileNode toFileNode(Object rawNode) {
        if (rawNode == null) {
            return null;
        }
        if (rawNode instanceof DataInfo.FileNode) {
            var node = (DataInfo.FileNode) rawNode;
            node.setFiles(normalizeContent(node.getFiles()));
            return node;
        }
        if (!(rawNode instanceof Map)) {
            return null;
        }

        var rawMap = (Map<String, Object>) rawNode;
        return DataInfo.FileNode.builder()
                .name(asString(rawMap.get("name")))
                .type(asString(rawMap.get("type")))
                .fileId(asLong(rawMap.get("fileId")))
                .files(normalizeContent((List<DataInfo.FileNode>) rawMap.get("files")))
                .build();
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private Long asLong(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        return Long.valueOf(String.valueOf(value));
    }
}
