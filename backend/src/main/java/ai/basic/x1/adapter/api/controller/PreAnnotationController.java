package ai.basic.x1.adapter.api.controller;

import ai.basic.x1.adapter.dto.*;
import ai.basic.x1.entity.PreAnnotationCreateBO;
import ai.basic.x1.usecase.PreAnnotationUseCase;
import ai.basic.x1.util.DefaultConverter;
import ai.basic.x1.util.Page;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/preAnnotation/")
public class PreAnnotationController extends BaseController {
    @Autowired private PreAnnotationUseCase useCase;

    @PostMapping("create")
    public Long create(@Validated @RequestBody PreAnnotationCreateDTO dto) {
        var bo = DefaultConverter.convert(dto, PreAnnotationCreateBO.class);
        if (loggedUser() != null) bo.setCreatedBy(loggedUser().getId());
        return useCase.create(bo);
    }

    @GetMapping("page")
    public Page<PreAnnotationRecordDTO> page(@RequestParam(defaultValue="1") Integer pageNo,
                                             @RequestParam(defaultValue="10") Integer pageSize) {
        return DefaultConverter.convert(useCase.page(pageNo, pageSize), PreAnnotationRecordDTO.class);
    }

    @GetMapping("{id}/data/{dataId}")
    public PreAnnotationFrameDTO frame(@PathVariable Long id, @PathVariable Long dataId) {
        return useCase.frame(id, dataId);
    }

    @GetMapping("{id}/data")
    public List<PreAnnotationFrameDTO> frames(@PathVariable Long id, @RequestParam List<Long> dataIds) {
        return useCase.frames(id, dataIds);
    }

    @PostMapping("{id}/commit")
    public PreAnnotationRecordDTO commit(@PathVariable Long id, @Validated @RequestBody PreAnnotationCommitDTO dto) {
        return DefaultConverter.convert(useCase.commit(id, dto.getDataIds(), loggedUser() == null ? null : loggedUser().getId()), PreAnnotationRecordDTO.class);
    }

    @PostMapping("delete/{id}")
    public void delete(@PathVariable Long id) {
        useCase.delete(id, loggedUser() == null ? null : loggedUser().getId());
    }
}
