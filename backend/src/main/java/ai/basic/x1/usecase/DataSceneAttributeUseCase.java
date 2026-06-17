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

@Component
public class DataSceneAttributeUseCase {

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
