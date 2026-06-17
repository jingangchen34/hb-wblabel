package ai.basic.x1.adapter.port.dao;

import ai.basic.x1.adapter.port.dao.mybatis.mapper.DataSceneAttributeMapper;
import ai.basic.x1.adapter.port.dao.mybatis.model.DataSceneAttribute;
import org.springframework.stereotype.Component;

@Component
public class DataSceneAttributeDAO extends AbstractDAO<DataSceneAttributeMapper, DataSceneAttribute> {
}
