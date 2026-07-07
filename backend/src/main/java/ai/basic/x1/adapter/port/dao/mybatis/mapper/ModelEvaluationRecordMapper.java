package ai.basic.x1.adapter.port.dao.mybatis.mapper;

import ai.basic.x1.adapter.port.dao.mybatis.model.ModelEvaluationRecord;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.annotations.Param;

public interface ModelEvaluationRecordMapper extends BaseMapper<ModelEvaluationRecord> {

    Page<ModelEvaluationRecord> selectListWithDatasetNotDeleted(Page<ModelEvaluationRecord> page,
                                                                @Param("ew") LambdaQueryWrapper<ModelEvaluationRecord> queryWrapper);
}
