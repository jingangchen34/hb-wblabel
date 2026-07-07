package ai.basic.x1.adapter.api.controller;

import ai.basic.x1.adapter.dto.ModelEvaluationCompareDTO;
import ai.basic.x1.adapter.dto.ModelEvaluationCreateDTO;
import ai.basic.x1.adapter.dto.ModelEvaluationRecordDTO;
import ai.basic.x1.entity.ModelEvaluationCreateBO;
import ai.basic.x1.usecase.ModelEvaluationUseCase;
import ai.basic.x1.util.DefaultConverter;
import ai.basic.x1.util.Page;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/modelEvaluation/")
public class ModelEvaluationController extends BaseController {

    @Autowired
    private ModelEvaluationUseCase modelEvaluationUseCase;

    @PostMapping("create")
    public Long create(@Validated @RequestBody ModelEvaluationCreateDTO dto) {
        var bo = DefaultConverter.convert(dto, ModelEvaluationCreateBO.class);
        var user = loggedUser();
        if (user != null) {
            bo.setCreatedBy(user.getId());
        }
        return modelEvaluationUseCase.create(bo);
    }

    @GetMapping("page")
    public Page<ModelEvaluationRecordDTO> page(@RequestParam Long modelId,
                                               @RequestParam(defaultValue = "1") Integer pageNo,
                                               @RequestParam(defaultValue = "10") Integer pageSize) {
        return DefaultConverter.convert(modelEvaluationUseCase.findByPage(modelId, pageNo, pageSize), ModelEvaluationRecordDTO.class);
    }

    @GetMapping("{evaluationId}/data/{dataId}/compare")
    public ModelEvaluationCompareDTO compare(@PathVariable Long evaluationId, @PathVariable Long dataId) {
        return modelEvaluationUseCase.compare(evaluationId, dataId);
    }
}
