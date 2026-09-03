package ai.basic.x1.adapter.port.dao.mybatis.mapper;

import ai.basic.x1.adapter.port.dao.mybatis.model.PreAnnotationRecord;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

public interface PreAnnotationRecordMapper extends BaseMapper<PreAnnotationRecord> {
    Page<PreAnnotationRecord> selectListWithDataset(Page<PreAnnotationRecord> page,
                                                     @Param("ew") LambdaQueryWrapper<PreAnnotationRecord> wrapper);
    @Update("UPDATE pre_annotation_record SET is_deleted=b'1', updated_by=#{userId} WHERE id=#{id}")
    int softDeleteById(@Param("id") Long id, @Param("userId") Long userId);
}
