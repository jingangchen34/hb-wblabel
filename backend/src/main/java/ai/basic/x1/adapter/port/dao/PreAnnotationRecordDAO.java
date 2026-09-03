package ai.basic.x1.adapter.port.dao;

import ai.basic.x1.adapter.port.dao.mybatis.mapper.PreAnnotationRecordMapper;
import ai.basic.x1.adapter.port.dao.mybatis.model.PreAnnotationRecord;
import org.springframework.stereotype.Component;

@Component
public class PreAnnotationRecordDAO extends AbstractDAO<PreAnnotationRecordMapper, PreAnnotationRecord> {
}
