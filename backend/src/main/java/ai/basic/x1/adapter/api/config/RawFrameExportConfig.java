package ai.basic.x1.adapter.api.config;

import ai.basic.x1.usecase.RawFrameExportUseCase;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RawFrameExportConfig {

    @Bean
    public RawFrameExportUseCase rawFrameExportUseCase() {
        return new RawFrameExportUseCase();
    }
}
