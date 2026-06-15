package ai.basic.x1.usecase;

import ai.basic.x1.adapter.port.dao.FileDAO;
import ai.basic.x1.adapter.port.dao.mybatis.model.File;
import ai.basic.x1.adapter.port.minio.MinioService;
import ai.basic.x1.entity.FileBO;
import ai.basic.x1.entity.RelationFileBO;
import ai.basic.x1.usecase.exception.UsecaseException;
import ai.basic.x1.util.DefaultConverter;
import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.util.ByteUtil;
import cn.hutool.crypto.SecureUtil;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * @author : fyb
 */
@Slf4j
public class FileUseCase {

    @Autowired
    private FileDAO fileDAO;

    @Autowired
    private MinioService minioService;

    /**
     * fileId
     *
     * @param id id
     * @return RelationFileBO
     */
    public RelationFileBO findById(Long id) {
        var file = fileDAO.getById(id);
        var lambdaQueryWrapper = Wrappers.lambdaQuery(File.class);
        lambdaQueryWrapper.eq(File::getRelationId, id);
        var relationFiles = fileDAO.list(lambdaQueryWrapper);
        var fileBO = DefaultConverter.convert(file, RelationFileBO.class);
        if (CollectionUtil.isNotEmpty(relationFiles)) {
            var relationFileBOs = DefaultConverter.convert(relationFiles, FileBO.class);
            relationFileBOs.forEach(this::setUrl);
            fileBO.setRelationFiles(relationFileBOs);
        }
        setUrl(fileBO);
        return fileBO;
    }

    /**
     * file object list
     *
     * @param ids file object ids
     * @return file object list
     */
    public List<RelationFileBO> findByIds(List<Long> ids) {
        var files = fileDAO.listByIds(ids);
        var fileBOs = DefaultConverter.convert(files, RelationFileBO.class);
        var lambdaQueryWrapper = Wrappers.lambdaQuery(File.class);
        lambdaQueryWrapper.in(File::getRelationId, ids);
        var relationFiles = fileDAO.list(lambdaQueryWrapper);
        Objects.requireNonNull(fileBOs).forEach(fileBO -> {
            setUrl(fileBO);
            if (CollectionUtil.isNotEmpty(relationFiles)) {
                var relationFileBOs = DefaultConverter.convert(relationFiles.stream().
                        filter(relationFile -> relationFile.getRelationId().equals(fileBO.getId())).collect(Collectors.toList()), FileBO.class);
                Objects.requireNonNull(relationFileBOs).forEach(this::setUrl);
                fileBO.setRelationFiles(relationFileBOs);
            }
        });
        return fileBOs;
    }


    private void setUrl(FileBO fileBO) {
        try {
            fileBO.setInternalUrl(minioService.getInternalUrl(fileBO.getBucketName(), fileBO.getPath()));
            fileBO.setUrl(minioService.getUrl(fileBO.getBucketName(), fileBO.getPath()));
        } catch (Exception e) {
            log.error("Get url error", e);
            throw new UsecaseException("Get url error");
        }
    }

    /**
     * batch save file
     *
     * @param fileBOS fileBOs
     * @return fileList
     */
    @Transactional(rollbackFor = Throwable.class)
    public synchronized List<FileBO> saveBatchFile(Long userId, List<FileBO> fileBOS) {
        var files = DefaultConverter.convert(fileBOS, File.class);
        Objects.requireNonNull(files).forEach(file -> {
            file.setPathHash(ByteUtil.bytesToLong(SecureUtil.md5().digest(file.getPath())));
            file.setCreatedBy(userId);
            file.setCreatedAt(OffsetDateTime.now());
            file.setUpdatedBy(userId);
            file.setUpdatedAt(OffsetDateTime.now());
        });

        Map<Long, File> fileMap = files.stream()
                .collect(Collectors.toMap(File::getPathHash, file -> file, (first, second) -> first, LinkedHashMap::new));
        var lambdaQueryWrapper = Wrappers.lambdaQuery(File.class);
        lambdaQueryWrapper.in(File::getPathHash, fileMap.keySet());
        var existingFiles = CollectionUtil.isEmpty(fileMap.keySet()) ? List.<File>of() : fileDAO.list(lambdaQueryWrapper);
        existingFiles.forEach(file -> fileMap.put(file.getPathHash(), file));

        var existingPathHashes = existingFiles.stream().map(File::getPathHash).collect(Collectors.toSet());
        var newFiles = files.stream()
                .filter(file -> !existingPathHashes.contains(file.getPathHash()))
                .collect(Collectors.toList());
        if (CollectionUtil.isNotEmpty(newFiles)) {
            fileDAO.saveBatch(newFiles);
            newFiles.forEach(file -> fileMap.put(file.getPathHash(), file));
        }

        var reFileBOs = DefaultConverter.convert(new ArrayList<>(fileMap.values()), FileBO.class);
        reFileBOs.forEach(fileBO -> setUrl(fileBO));
        return reFileBOs;
    }
}
