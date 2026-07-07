package ai.basic.x1.adapter.port.dao;

import ai.basic.x1.adapter.port.dao.mybatis.mapper.ModelEvaluationRecordMapper;
import ai.basic.x1.adapter.port.dao.mybatis.model.ModelEvaluationRecord;
import org.springframework.stereotype.Component;

@Component
public class ModelEvaluationRecordDAO extends AbstractDAO<ModelEvaluationRecordMapper, ModelEvaluationRecord> {
}
