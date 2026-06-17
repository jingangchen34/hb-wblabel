<template>
    <div v-if="isViewMode" class="scene-attribute-panel">
        <div class="panel-title">Scene Attribute</div>
        <div class="group" v-for="group in groups" :key="group.value">
            <button
                :class="['group-title', { active: state.category === group.value }]"
                @click="selectCategory(group.value)"
            >
                {{ group.label }}
            </button>
            <div v-if="state.category === group.value" class="sub-list">
                <button
                    v-for="item in group.children"
                    :key="item.value"
                    :class="['sub-item', { active: state.subType === item.value }]"
                    @click="selectSubType(group.value, item.value)"
                >
                    {{ item.label }}
                </button>
            </div>
        </div>
        <div class="actions">
            <button :disabled="state.saving" @click="clearAttribute">Clear</button>
            <button :disabled="state.saving || !state.category || !state.subType" @click="saveAttribute">
                {{ state.saving ? 'Saving' : 'Save' }}
            </button>
        </div>
        <div class="current" v-if="currentLabel">Current: {{ currentLabel }}</div>
    </div>
</template>

<script setup lang="ts">
    import { computed, onMounted, reactive } from 'vue';
    import { useInjectEditor } from '../../../state';
    import * as api from '../../../api';

    const groups = [
        {
            value: 'noise',
            label: 'noise',
            children: [
                { value: 'dust', label: '灰尘' },
                { value: 'splash', label: '水花' },
                { value: 'sprinkler', label: '对象洒水车' },
            ],
        },
        {
            value: 'stationary',
            label: 'stationary',
            children: [
                { value: 'discharge_guardrail', label: '卸料口护栏' },
                { value: 'fence', label: '围栏' },
            ],
        },
        {
            value: 'unfree',
            label: 'unfree',
            children: [
                { value: 'retaining_wall', label: '挡墙' },
                { value: 'discharge_port', label: '卸料口' },
                { value: 'shoveling', label: '铲装' },
            ],
        },
    ];

    const editor = useInjectEditor();
    const state = reactive({
        category: '',
        subType: '',
        saving: false,
    });

    const isViewMode = computed(() => editor.bsState.query.type === 'readOnly');
    const currentDataId = computed(() => editor.getCurrentFrame()?.id || editor.bsState.query.dataId || '');
    const currentLabel = computed(() => {
        const group = groups.find((item) => item.value === state.category);
        const sub = group?.children.find((item) => item.value === state.subType);
        if (!group || !sub) return '';
        return `${group.label} / ${sub.label}`;
    });

    onMounted(loadAttribute);

    function selectCategory(category: string) {
        state.category = category;
        if (!groups.find((group) => group.value === category)?.children.some((item) => item.value === state.subType)) {
            state.subType = '';
        }
    }

    function selectSubType(category: string, subType: string) {
        state.category = category;
        state.subType = subType;
    }

    async function loadAttribute() {
        if (!isViewMode.value || !currentDataId.value) return;
        try {
            const attribute = await api.getSceneAttribute(currentDataId.value);
            state.category = attribute.category || '';
            state.subType = attribute.subType || '';
        } catch (error: any) {
            editor.handleErr(error);
        }
    }

    async function saveAttribute() {
        if (!currentDataId.value) return;
        state.saving = true;
        try {
            await api.saveSceneAttribute({
                datasetId: editor.bsState.datasetId,
                dataId: currentDataId.value,
                category: state.category,
                subType: state.subType,
            });
            editor.showMsg('success', 'Scene attribute saved');
        } catch (error: any) {
            editor.handleErr(error);
        } finally {
            state.saving = false;
        }
    }

    async function clearAttribute() {
        state.category = '';
        state.subType = '';
        await saveAttribute();
    }
</script>

<style lang="less" scoped>
    .scene-attribute-panel {
        padding: 12px 14px;
        border-bottom: 1px solid #2f3036;
        color: #d9d9df;

        .panel-title {
            margin-bottom: 8px;
            font-size: 16px;
            font-weight: 600;
        }

        .group {
            margin-bottom: 6px;
        }

        button {
            border: 1px solid #4a4d57;
            background: #2a2c33;
            color: #e6e6ea;
            cursor: pointer;

            &:disabled {
                cursor: not-allowed;
                opacity: 0.55;
            }
        }

        .group-title {
            width: 100%;
            padding: 6px 8px;
            text-align: left;
            font-weight: 600;

            &.active {
                border-color: #2f80ed;
                background: #243a62;
            }
        }

        .sub-list {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 6px;
            margin-top: 6px;
        }

        .sub-item {
            min-width: 0;
            padding: 5px 6px;

            &.active {
                border-color: #2f80ed;
                background: #2c4a80;
            }
        }

        .actions {
            display: flex;
            gap: 8px;
            margin-top: 10px;

            button {
                flex: 1;
                padding: 6px;
            }
        }

        .current {
            margin-top: 8px;
            color: #aeb3c2;
            font-size: 12px;
        }
    }
</style>
