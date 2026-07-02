package ai.basic.x1.adapter.port.dao.mybatis.mapper;

import ai.basic.x1.adapter.port.dao.mybatis.model.Dataset;
import ai.basic.x1.adapter.port.dao.mybatis.model.DatasetSourceAttributeStatistics;
import ai.basic.x1.adapter.port.dao.mybatis.model.DatasetSourceClassStatistics;
import ai.basic.x1.adapter.port.dao.mybatis.model.DatasetSourceMineStatistics;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.toolkit.Constants;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.io.Serializable;
import java.util.List;

/**
 * @author fyb
 * @date 2022-02-16 10:17:54
 */
@Mapper
public interface DatasetMapper extends BaseMapper<Dataset> {

    /**
     * Paging query dataset according to query conditions
     *
     * @param page         Pagination information
     * @param queryWrapper Query conditions
     * @return Dataset paging information
     */
    Page<Dataset> selectDatasetPage(Page<Dataset> page, @Param(Constants.WRAPPER) Wrapper<Dataset> queryWrapper);

    Long countObject(@Param("datasetId") Long datasetId);

    List<DatasetSourceMineStatistics> statisticsSourceMine(@Param("sourceName") String sourceName);

    List<DatasetSourceClassStatistics> statisticsSourceClassTotal(@Param("sourceName") String sourceName);

    List<DatasetSourceClassStatistics> statisticsSourceClassByMine(@Param("sourceName") String sourceName);

    List<DatasetSourceAttributeStatistics> statisticsSourceAttributeByMine(@Param("sourceName") String sourceName);

    /**
     * This method overrides the deleteById method of baseMapper
     *
     * @param id
     */
    @Override
    int deleteById(Serializable id);
}
