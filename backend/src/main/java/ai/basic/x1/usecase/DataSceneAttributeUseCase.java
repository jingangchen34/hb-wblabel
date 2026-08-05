package ai.basic.x1.usecase;

import ai.basic.x1.adapter.port.dao.DataInfoDAO;
import ai.basic.x1.adapter.port.dao.DataSceneAttributeDAO;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataInfo;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataSceneAttribute;
import ai.basic.x1.entity.DataSceneAttributeBO;
import ai.basic.x1.entity.enums.ItemTypeEnum;
import ai.basic.x1.usecase.exception.UsecaseCode;
import ai.basic.x1.usecase.exception.UsecaseException;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Component
public class DataSceneAttributeUseCase {
    public static final String FRAME_TAG_CATEGORY = "capture_condition";
    private static final Set<String> FRAME_TAGS = Set.of("splash", "rut", "dust");


    @Autowired
    private DataInfoDAO dataInfoDAO;

    @Autowired
    private DataSceneAttributeDAO dataSceneAttributeDAO;

    public DataSceneAttributeBO findByDataId(Long dataId) {
        var scene = resolveScene(dataId);
        var attribute = dataSceneAttributeDAO.getOne(Wrappers.lambdaQuery(DataSceneAttribute.class)
                .eq(DataSceneAttribute::getDataId, scene.getId()));
        if (attribute == null) {
            return DataSceneAttributeBO.builder()
                    .datasetId(scene.getDatasetId())
                    .dataId(scene.getId())
                    .build();
        }

        return DataSceneAttributeBO.builder()
                .datasetId(attribute.getDatasetId())
                .dataId(attribute.getDataId())
                .category(attribute.getCategory())
                .subType(attribute.getSubType())
                .build();
    }

    public void save(DataSceneAttributeBO attributeBO, Long userId) {
        var scene = resolveScene(attributeBO.getDataId());
        if (StrUtil.isBlank(attributeBO.getCategory()) || StrUtil.isBlank(attributeBO.getSubType())) {
            dataSceneAttributeDAO.remove(Wrappers.lambdaQuery(DataSceneAttribute.class)
                    .eq(DataSceneAttribute::getDataId, scene.getId()));
            return;
        }

        var oldAttribute = dataSceneAttributeDAO.getOne(Wrappers.lambdaQuery(DataSceneAttribute.class)
                .eq(DataSceneAttribute::getDataId, scene.getId()));
        var attribute = DataSceneAttribute.builder()
                .id(oldAttribute == null ? null : oldAttribute.getId())
                .datasetId(scene.getDatasetId())
                .dataId(scene.getId())
                .category(attributeBO.getCategory())
                .subType(attributeBO.getSubType())
                .updatedBy(userId)
                .build();
        if (oldAttribute == null) {
            attribute.setCreatedBy(userId);
        }
        dataSceneAttributeDAO.saveOrUpdate(attribute);
    }

    public DataSceneAttributeBO findFrameTag(Long dataId) {
        var frame = resolveFrame(dataId);
        var attribute = dataSceneAttributeDAO.getOne(Wrappers.lambdaQuery(DataSceneAttribute.class)
                .eq(DataSceneAttribute::getDataId, frame.getId())
                .eq(DataSceneAttribute::getCategory, FRAME_TAG_CATEGORY));
        if (attribute == null) {
            return DataSceneAttributeBO.builder()
                    .datasetId(frame.getDatasetId())
                    .dataId(frame.getId())
                    .category(FRAME_TAG_CATEGORY)
                    .build();
        }
        return DataSceneAttributeBO.builder()
                .datasetId(attribute.getDatasetId())
                .dataId(attribute.getDataId())
                .category(attribute.getCategory())
                .subType(attribute.getSubType())
                .build();
    }

    public void saveFrameTag(DataSceneAttributeBO attributeBO, Long userId) {
        var frame = resolveFrame(attributeBO.getDataId());
        var tag = normalizeFrameTag(attributeBO.getSubType(), true);
        var wrapper = Wrappers.lambdaQuery(DataSceneAttribute.class)
                .eq(DataSceneAttribute::getDataId, frame.getId());
        if (tag == null) {
            dataSceneAttributeDAO.remove(wrapper);
            return;
        }

        var oldAttribute = dataSceneAttributeDAO.getOne(wrapper);
        var attribute = DataSceneAttribute.builder()
                .id(oldAttribute == null ? null : oldAttribute.getId())
                .datasetId(frame.getDatasetId())
                .dataId(frame.getId())
                .category(FRAME_TAG_CATEGORY)
                .subType(tag)
                .updatedBy(userId)
                .build();
        if (oldAttribute == null) {
            attribute.setCreatedBy(userId);
        }
        dataSceneAttributeDAO.saveOrUpdate(attribute);
    }

    public List<Long> findTaggedFrameIds(Long datasetId, Long sceneId, List<String> requestedTags) {
        var tags = requestedTags.stream()
                .map(tag -> normalizeFrameTag(tag, false))
                .collect(Collectors.toSet());
        var attributes = dataSceneAttributeDAO.list(Wrappers.lambdaQuery(DataSceneAttribute.class)
                .eq(DataSceneAttribute::getDatasetId, datasetId)
                .eq(DataSceneAttribute::getCategory, FRAME_TAG_CATEGORY)
                .in(DataSceneAttribute::getSubType, tags));
        if (attributes.isEmpty()) {
            return List.of();
        }

        var dataIds = attributes.stream().map(DataSceneAttribute::getDataId).collect(Collectors.toSet());
        return dataInfoDAO.listByIds(dataIds).stream()
                .filter(data -> datasetId.equals(data.getDatasetId()))
                .filter(data -> ItemTypeEnum.SINGLE_DATA.equals(data.getType()))
                .filter(data -> !Boolean.TRUE.equals(data.getIsDeleted()))
                .filter(data -> sceneId == null || sceneId.equals(data.getParentId()))
                .sorted((left, right) -> {
                    var leftOrder = StrUtil.blankToDefault(left.getOrderName(), left.getName());
                    var rightOrder = StrUtil.blankToDefault(right.getOrderName(), right.getName());
                    var result = leftOrder.compareTo(rightOrder);
                    return result == 0 ? left.getId().compareTo(right.getId()) : result;
                })
                .map(DataInfo::getId)
                .collect(Collectors.toList());
    }

    public Map<String, Long> countFrameTags(Long datasetId, Long sceneId) {
        var result = new LinkedHashMap<String, Long>();
        for (var tag : List.of("splash", "rut", "dust")) {
            result.put(tag, (long) findTaggedFrameIds(datasetId, sceneId, List.of(tag)).size());
        }
        return result;
    }

    private String normalizeFrameTag(String tag, boolean allowBlank) {
        if (StrUtil.isBlank(tag)) {
            if (allowBlank) {
                return null;
            }
            throw new UsecaseException("frame tag cannot be blank");
        }
        var normalized = tag.trim().toLowerCase(Locale.ROOT);
        if (!FRAME_TAGS.contains(normalized)) {
            throw new UsecaseException("unsupported frame tag: " + tag);
        }
        return normalized;
    }

    private DataInfo resolveFrame(Long dataId) {
        var frame = dataInfoDAO.getById(dataId);
        if (frame == null || !ItemTypeEnum.SINGLE_DATA.equals(frame.getType()) || Boolean.TRUE.equals(frame.getIsDeleted())) {
            throw new UsecaseException("frame not found: " + dataId);
        }
        return frame;
    }
    private DataInfo resolveScene(Long dataId) {
        var dataInfo = dataInfoDAO.getById(dataId);
        if (dataInfo == null) {
            throw new UsecaseException(UsecaseCode.NOT_FOUND);
        }
        if (ItemTypeEnum.SCENE.equals(dataInfo.getType())) {
            return dataInfo;
        }
        if (dataInfo.getParentId() == null || dataInfo.getParentId() == 0) {
            return dataInfo;
        }
        var scene = dataInfoDAO.getById(dataInfo.getParentId());
        if (scene == null) {
            throw new UsecaseException(UsecaseCode.NOT_FOUND);
        }
        return scene;
    }
}
