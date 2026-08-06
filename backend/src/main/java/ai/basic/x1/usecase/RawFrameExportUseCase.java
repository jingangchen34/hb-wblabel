package ai.basic.x1.usecase;

import ai.basic.x1.adapter.port.dao.DatasetDAO;
import ai.basic.x1.adapter.port.dao.ExportRecordDAO;
import ai.basic.x1.adapter.port.dao.mybatis.model.ExportRecord;
import ai.basic.x1.adapter.port.minio.MinioProp;
import ai.basic.x1.adapter.port.minio.MinioService;
import ai.basic.x1.entity.DataInfoBO;
import ai.basic.x1.entity.ExportRecordBO;
import ai.basic.x1.entity.FileBO;
import ai.basic.x1.entity.RelationFileBO;
import ai.basic.x1.entity.enums.ExportStatusEnum;
import ai.basic.x1.usecase.exception.UsecaseException;
import cn.hutool.core.collection.CollUtil;
import cn.hutool.core.date.DatePattern;
import cn.hutool.core.date.TemporalAccessorUtil;
import cn.hutool.core.io.FileUtil;
import cn.hutool.core.thread.ThreadUtil;
import cn.hutool.core.util.IdUtil;
import cn.hutool.core.util.ZipUtil;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.alibaba.ttl.TtlRunnable;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/** Export manually tagged frames while preserving the imported raw clip layout. */
@Component
@Slf4j
public class RawFrameExportUseCase {

    private static final String EXTERNAL_BUCKET = "external-data";
    private static final Pattern FRAME_TOKEN = Pattern.compile("(\\d{10,})");
    private static final Set<String> STATIC_METADATA = Set.of(
            "calib.json", "calib_cylindrical.json");
    private static final ExecutorService EXECUTOR = ThreadUtil.newExecutor(2);

    @Autowired
    private DataInfoUseCase dataInfoUseCase;
    @Autowired
    private DatasetDAO datasetDAO;
    @Autowired
    private ExportRecordDAO exportRecordDAO;
    @Autowired
    private ExportRecordUseCase exportRecordUseCase;
    @Autowired
    private MinioService minioService;
    @Autowired
    private MinioProp minioProp;
    @Autowired
    private FileUseCase fileUseCase;

    @Value("${file.tempPath:/tmp/xtreme1/}")
    private String tempPath;

    @Value("${external.data.root:/external-data}")
    private String externalDataRoot;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public Long export(Long datasetId, List<Long> frameIds) {
        if (CollUtil.isEmpty(frameIds)) {
            throw new UsecaseException("no tagged frames matched the selected labels");
        }
        var dataset = datasetDAO.getById(datasetId);
        if (dataset == null) {
            throw new UsecaseException("dataset not found: " + datasetId);
        }
        var fileName = resolveOriginalPackageName(dataset.getName(), frameIds) + ".zip";
        var serialNumber = IdUtil.getSnowflakeNextId();
        exportRecordDAO.save(ExportRecord.builder()
                .serialNumber(serialNumber)
                .fileName(fileName)
                .status(ExportStatusEnum.GENERATING)
                .generatedNum(0)
                .totalNum(frameIds.size())
                .build());
        EXECUTOR.execute(Objects.requireNonNull(TtlRunnable.get(
                () -> generate(serialNumber, fileName, dataset.getName(), frameIds))));
        return serialNumber;
    }

    private void generate(Long serialNumber, String fileName, String datasetName, List<Long> frameIds) {
        var record = exportRecordDAO.getOne(Wrappers.lambdaQuery(ExportRecord.class)
                .eq(ExportRecord::getSerialNumber, serialNumber));
        var workDir = Path.of(tempPath, "raw-selection-" + serialNumber);
        var packageName = fileName.toLowerCase().endsWith(".zip")
                ? fileName.substring(0, fileName.length() - 4) : fileName;
        var packageDir = workDir.resolve(safeName(packageName));
        var zipPath = Path.of(workDir.toString() + ".zip");
        try {
            Files.createDirectories(packageDir);
            var frames = dataInfoUseCase.listByIds(frameIds, false);
            var sceneIds = frames.stream().map(DataInfoBO::getParentId)
                    .filter(Objects::nonNull).filter(id -> id != 0).collect(Collectors.toSet());
            var scenes = dataInfoUseCase.listByIds(new ArrayList<>(sceneIds), false).stream()
                    .collect(Collectors.toMap(DataInfoBO::getId, scene -> scene));

            var byScene = frames.stream().collect(Collectors.groupingBy(DataInfoBO::getParentId,
                    LinkedHashMap::new, Collectors.toList()));
            var multipleScenes = byScene.size() > 1;
            var completed = 0;
            for (var entry : byScene.entrySet()) {
                var scene = scenes.get(entry.getKey());
                var sceneName = scene == null ? "scene-" + entry.getKey() : scene.getName();
                var sceneDir = multipleScenes ? safeResolve(packageDir, safeName(sceneName)) : packageDir;
                var sceneFrames = entry.getValue();
                sceneFrames.sort(Comparator.comparing(frame -> Objects.toString(frame.getOrderName(), frame.getName())));
                exportScene(sceneDir, sceneFrames);
                completed += sceneFrames.size();
                updateProgress(record, completed, frames.size());
            }

            var zipFile = ZipUtil.zip(workDir.toString(), zipPath.toString(), false);
            var objectPath = String.format("%s/%s/%s", record.getCreatedBy(),
                    TemporalAccessorUtil.format(OffsetDateTime.now(), DatePattern.PURE_DATETIME_PATTERN),
                    zipFile.getName());
            minioService.uploadFile(minioProp.getBucketName(), objectPath, FileUtil.getInputStream(zipFile),
                    "application/zip", zipFile.length());
            var savedFiles = fileUseCase.saveBatchFile(record.getCreatedBy(), Collections.singletonList(
                    FileBO.builder().name(zipFile.getName()).originalName(zipFile.getName())
                            .bucketName(minioProp.getBucketName()).size(zipFile.length())
                            .path(objectPath).type("application/zip").build()));
            var completedRecord = ExportRecordBO.builder()
                    .id(record.getId()).fileId(savedFiles.get(0).getId())
                    .status(ExportStatusEnum.COMPLETED).generatedNum(frames.size())
                    .totalNum(frames.size()).updatedBy(record.getCreatedBy()).updatedAt(OffsetDateTime.now()).build();
            exportRecordUseCase.saveOrUpdate(completedRecord);
        } catch (Exception error) {
            log.error("Export selected raw frames failed, serialNumber={}", serialNumber, error);
            exportRecordUseCase.saveOrUpdate(ExportRecordBO.builder().id(record.getId())
                    .status(ExportStatusEnum.FAILED).updatedBy(record.getCreatedBy())
                    .updatedAt(OffsetDateTime.now()).build());
        } finally {
            FileUtil.del(workDir.toFile());
            FileUtil.del(zipPath.toFile());
        }
    }

    private void exportScene(Path destination, List<DataInfoBO> frames) throws IOException {
        Files.createDirectories(destination);
        var clipRoot = findClipRoot(frames);
        if (clipRoot == null) {
            throw new IOException("cannot resolve original clip directory for frame " + frames.get(0).getName());
        }
        var selectedTokens = frames.stream().map(frame -> frameToken(frame.getName()))
                .filter(Objects::nonNull).collect(Collectors.toCollection(HashSet::new));

        for (var frame : frames) {
            for (var file : flattenFiles(frame.getContent())) {
                var source = externalSource(file);
                if (source == null || !Files.isRegularFile(source) || !source.startsWith(clipRoot)) {
                    continue;
                }
                var name = source.getFileName().toString();
                if ("pose.json".equalsIgnoreCase(name) || "obstacle_3d.json".equalsIgnoreCase(name)) {
                    continue;
                }
                copy(source, safeResolve(destination, clipRoot.relativize(source).toString()));
            }
        }

        for (var metadata : STATIC_METADATA) {
            var source = clipRoot.resolve(metadata);
            if (Files.isRegularFile(source)) {
                copy(source, destination.resolve(metadata));
            }
        }
        var poseTokens = filterMetaJson(clipRoot.resolve("meta.json"), destination.resolve("meta.json"),
                selectedTokens);
        filterPoseJson(clipRoot.resolve("pose.json"), destination.resolve("pose.json"), poseTokens);
        filterFrameJson(clipRoot.resolve("anno").resolve("obstacle_3d.json"),
                destination.resolve("anno").resolve("obstacle_3d.json"),
                clipRoot, destination, selectedTokens, true);
    }

    private String resolveOriginalPackageName(String datasetName, List<Long> frameIds) {
        var frames = dataInfoUseCase.listByIds(frameIds, false);
        var sceneIds = frames.stream().map(DataInfoBO::getParentId)
                .filter(Objects::nonNull).filter(id -> id != 0).distinct().collect(Collectors.toList());
        String originalName = datasetName;
        if (sceneIds.size() == 1) {
            var scenes = dataInfoUseCase.listByIds(sceneIds, false);
            if (!scenes.isEmpty()) originalName = scenes.get(0).getName();
        }
        var normalized = Objects.toString(originalName, "dataset");
        var slash = normalized.lastIndexOf('/');
        return safeName(slash >= 0 ? normalized.substring(slash + 1) : normalized);
    }

    private Set<String> filterMetaJson(Path source, Path destination, Set<String> selectedLidarTokens)
            throws IOException {
        if (!Files.isRegularFile(source)) return new HashSet<>(selectedLidarTokens);
        var root = objectMapper.readTree(source.toFile());
        if (!(root instanceof ObjectNode) || !root.path("key_frame").isObject()) {
            throw new IOException("invalid meta.json structure: " + source);
        }
        var keyFrame = (ObjectNode) root.path("key_frame");
        JsonNode lidarFrames = keyFrame.get("LIDAR_TOP");
        if (lidarFrames == null || !lidarFrames.isArray()) {
            throw new IOException("meta.json has no key_frame.LIDAR_TOP array: " + source);
        }

        var selectedIndices = new ArrayList<Integer>();
        for (var index = 0; index < lidarFrames.size(); index++) {
            var token = frameToken(lidarFrames.get(index).asText());
            if (token != null && selectedLidarTokens.contains(token)) selectedIndices.add(index);
        }
        if (selectedIndices.isEmpty()) {
            throw new IOException("selected frame indices were not found in meta.json: " + source);
        }

        ObjectNode output = ((ObjectNode) root).deepCopy();
        ObjectNode outputKeyFrame = (ObjectNode) output.path("key_frame");
        var poseTokens = new HashSet<String>();
        var sensors = keyFrame.fields();
        while (sensors.hasNext()) {
            var sensor = sensors.next();
            if (!sensor.getValue().isArray()) continue;
            ArrayNode filtered = objectMapper.createArrayNode();
            for (var index : selectedIndices) {
                if (index >= sensor.getValue().size()) {
                    throw new IOException("meta.json sensor index mismatch for " + sensor.getKey() + ": " + source);
                }
                var value = sensor.getValue().get(index);
                filtered.add(value.deepCopy());
                if (value.isTextual()) {
                    var token = frameToken(value.asText());
                    if (token != null) poseTokens.add(token);
                }
            }
            outputKeyFrame.set(sensor.getKey(), filtered);
        }
        if (output.has("duration")) output.put("duration", selectedIndices.size());
        Files.createDirectories(destination.getParent());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(destination.toFile(), output);
        return poseTokens;
    }

    private void filterPoseJson(Path source, Path destination, Set<String> selectedPoseTokens) throws IOException {
        if (!Files.isRegularFile(source)) return;
        var root = objectMapper.readTree(source.toFile());
        if (!root.isObject()) throw new IOException("invalid pose.json structure: " + source);
        var output = objectMapper.createObjectNode();
        var fields = root.fields();
        while (fields.hasNext()) {
            var field = fields.next();
            if (selectedPoseTokens.contains(field.getKey())) {
                output.set(field.getKey(), field.getValue());
            }
        }
        if (output.isEmpty()) {
            throw new IOException("selected frame poses were not found in pose.json: " + source);
        }
        Files.createDirectories(destination.getParent());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(destination.toFile(), output);
    }

    private Path findClipRoot(List<DataInfoBO> frames) {
        for (var frame : frames) {
            for (var file : flattenFiles(frame.getContent())) {
                var source = externalSource(file);
                if (source == null) continue;
                var current = source.getParent();
                for (var depth = 0; current != null && depth < 8; depth++, current = current.getParent()) {
                    if (Files.isRegularFile(current.resolve("calib.json"))
                            || Files.isRegularFile(current.resolve("pose.json"))
                            || Files.isDirectory(current.resolve("lidars"))) {
                        return current.normalize();
                    }
                }
            }
        }
        return null;
    }

    private List<RelationFileBO> flattenFiles(List<DataInfoBO.FileNodeBO> nodes) {
        var files = new ArrayList<RelationFileBO>();
        if (nodes == null) return files;
        for (var node : nodes) {
            if ("file".equals(node.getType()) && node.getFile() != null) {
                files.add(node.getFile());
            } else {
                files.addAll(flattenFiles(node.getFiles()));
            }
        }
        return files;
    }

    private Path externalSource(RelationFileBO file) {
        if (file == null || !EXTERNAL_BUCKET.equals(file.getBucketName()) || file.getPath() == null) return null;
        var root = Path.of(externalDataRoot).toAbsolutePath().normalize();
        var source = root.resolve(file.getPath()).normalize();
        return source.startsWith(root) ? source : null;
    }

    private void filterFrameJson(Path source, Path destination, Path clipRoot, Path outputRoot,
                                 Set<String> selectedTokens, boolean copyReferencedFiles) throws IOException {
        if (!Files.isRegularFile(source)) return;
        var root = objectMapper.readTree(source.toFile());
        if (!root.isObject()) {
            copy(source, destination);
            return;
        }
        var output = objectMapper.createObjectNode();
        var selected = new ArrayList<Map.Entry<String, JsonNode>>();
        var fields = root.fields();
        while (fields.hasNext()) {
            var field = fields.next();
            if (isFrameEntry(field.getKey(), field.getValue())) {
                if (matchesSelected(field.getKey(), field.getValue(), selectedTokens)) selected.add(field);
            } else if (!"first_frame".equals(field.getKey())) {
                output.set(field.getKey(), field.getValue());
            }
        }
        if (selected.isEmpty()) {
            copy(source, destination);
            return;
        }
        output.put("first_frame", selected.get(0).getKey());
        for (var index = 0; index < selected.size(); index++) {
            var field = selected.get(index);
            var value = field.getValue().deepCopy();
            if (value instanceof ObjectNode) {
                ((ObjectNode) value).put("prev_time_file", index == 0 ? null : selected.get(index - 1).getKey());
                ((ObjectNode) value).put("next_time_file", index + 1 >= selected.size() ? null : selected.get(index + 1).getKey());
            }
            output.set(field.getKey(), value);
            if (copyReferencedFiles) copyReferencedFiles(value, clipRoot, outputRoot);
        }
        Files.createDirectories(destination.getParent());
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(destination.toFile(), output);
    }

    private boolean isFrameEntry(String key, JsonNode value) {
        return value.isObject() && (key.matches("\\d{10,}") || value.has("filepath")
                || value.has("cam_files") || value.has("annotations"));
    }

    private boolean matchesSelected(String key, JsonNode value, Set<String> tokens) {
        for (var token : tokens) {
            if (key.contains(token) || value.toString().contains(token)) return true;
        }
        return false;
    }

    private void copyReferencedFiles(JsonNode node, Path clipRoot, Path outputRoot) throws IOException {
        if (node.isTextual()) {
            var value = node.asText().replace('\\', '/');
            if (!value.contains("/") || value.startsWith("http://") || value.startsWith("https://")) return;
            var source = clipRoot.resolve(value).normalize();
            if (source.startsWith(clipRoot) && Files.isRegularFile(source)) {
                copy(source, safeResolve(outputRoot, value));
            }
            return;
        }
        var children = node.elements();
        while (children.hasNext()) copyReferencedFiles(children.next(), clipRoot, outputRoot);
    }

    private void updateProgress(ExportRecord record, int generated, int total) {
        exportRecordUseCase.saveOrUpdate(ExportRecordBO.builder().id(record.getId())
                .generatedNum(generated).totalNum(total).status(ExportStatusEnum.GENERATING)
                .updatedBy(record.getCreatedBy()).updatedAt(OffsetDateTime.now()).build());
    }

    private String frameToken(String name) {
        if (name == null) return null;
        Matcher matcher = FRAME_TOKEN.matcher(name);
        String token = null;
        while (matcher.find()) token = matcher.group(1);
        return token;
    }

    private void copy(Path source, Path destination) throws IOException {
        Files.createDirectories(destination.getParent());
        Files.copy(source, destination, StandardCopyOption.REPLACE_EXISTING);
    }

    private Path safeResolve(Path root, String relative) throws IOException {
        var destination = root.resolve(relative).normalize();
        if (!destination.startsWith(root.normalize())) throw new IOException("unsafe export path: " + relative);
        return destination;
    }

    private String safeName(String value) {
        var safe = Objects.toString(value, "dataset").replaceAll("[\\\\/:*?\"<>|]", "_").trim();
        return safe.isEmpty() ? "dataset" : safe;
    }
}
