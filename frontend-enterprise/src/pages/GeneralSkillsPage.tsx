import { CloudOutlined, ExperimentOutlined, UploadOutlined } from '@ant-design/icons';
import { Button, Card, Input, Select, Space, Table, Tag, Typography, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { api, TENANT_ID } from '../api/client';
import type { GeneralSkillRead, GeneralSkillRunResponse } from '../types';

const DEFAULT_MARKDOWN = `---
name: 中国城市天气
slug: weather-zh
description: 中国城市天气查询工具
homepage: https://www.weather.com.cn/
---

# 中国城市天气查询工具

输入城市名称，查询城市天气。`;

export default function GeneralSkillsPage({ embedded = false }: { embedded?: boolean }) {
  const [rows, setRows] = useState<GeneralSkillRead[]>([]);
  const [markdown, setMarkdown] = useState(DEFAULT_MARKDOWN);
  const [selectedSlug, setSelectedSlug] = useState<string>();
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [query, setQuery] = useState('北京今天天气怎么样');
  const [runResult, setRunResult] = useState<GeneralSkillRunResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedSkill = useMemo(
    () => rows.find((row) => row.slug === selectedSlug) || rows[0],
    [rows, selectedSlug],
  );

  const load = () =>
    api
      .get<GeneralSkillRead[]>(`/api/enterprise/general-skills?tenant_id=${TENANT_ID}`)
      .then((items) => {
        setRows(items);
        if (!selectedSlug && items.length) setSelectedSlug(items[0].slug);
      })
      .catch((error) => message.error(error.message));

  useEffect(() => {
    load();
  }, []);

  async function importSkill() {
    if (!markdown.trim()) {
      message.warning('请先粘贴或上传 SKILL.md');
      return;
    }
    const row = await api.post<GeneralSkillRead>('/api/enterprise/general-skills/import', {
      tenant_id: TENANT_ID,
      markdown,
      status: 'published',
    });
    message.success(editingSlug ? `已保存 ${row.name}` : `已导入 ${row.name}`);
    setSelectedSlug(row.slug);
    setEditingSlug(row.slug);
    load();
  }

  function newSkill() {
    setMarkdown(DEFAULT_MARKDOWN);
    setEditingSlug(null);
    setRunResult(null);
  }

  function editSkill(row: GeneralSkillRead) {
    setMarkdown(row.skill_markdown);
    setSelectedSlug(row.slug);
    setEditingSlug(row.slug);
    setRunResult(null);
  }

  async function runSkill() {
    const slug = selectedSkill?.slug;
    if (!slug) {
      message.warning('请先导入通用技能');
      return;
    }
    if (!query.trim()) {
      message.warning('请输入测试问题');
      return;
    }
    setLoading(true);
    setRunResult(null);
    try {
      const result = await api.post<GeneralSkillRunResponse>(`/api/enterprise/general-skills/${slug}/run`, {
        tenant_id: TENANT_ID,
        user_id: 'enterprise_demo',
        query,
      });
      setRunResult(result);
      message.success('运行完成');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '运行失败');
    } finally {
      setLoading(false);
    }
  }

  async function beforeUpload(file: UploadFile | File) {
    const target = file as File;
    const text = await target.text();
    setMarkdown(text);
    message.success(`已读取 ${target.name}`);
    return false;
  }

  const columns: ColumnsType<GeneralSkillRead> = [
    { title: '名称', dataIndex: 'name', width: 180, ellipsis: true },
    { title: 'Slug', dataIndex: 'slug', width: 160, ellipsis: true },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 100, render: (value) => <Tag color="green">{value}</Tag> },
    {
      title: '操作',
      width: 96,
      render: (_, row) => <Button size="small" onClick={() => editSkill(row)}>编辑</Button>,
    },
  ];

  return (
    <>
      {!embedded && (
        <div className="page-title">
          <Typography.Title level={3}>通用技能 Demo</Typography.Title>
          <Typography.Text type="secondary">导入 PilotDeck 风格 SKILL.md，验证模型选择、代码生成与运行链路。</Typography.Text>
        </div>
      )}
      <div className="grid-2">
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card
            className="editor-card"
            title={editingSlug ? `编辑通用技能：${editingSlug}` : '新增通用技能'}
            extra={(
              <Space>
                <Button onClick={newSkill}>新建</Button>
                <Upload beforeUpload={beforeUpload} showUploadList={false} accept=".md,.txt">
                  <Button icon={<UploadOutlined />}>选择文件</Button>
                </Upload>
                <Button type="primary" icon={<CloudOutlined />} onClick={importSkill}>保存并发布</Button>
              </Space>
            )}
          >
            <Input.TextArea
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
              rows={16}
              spellCheck={false}
            />
          </Card>
          <Card
            className="editor-card"
            title="运行测试"
            extra={<Button type="primary" loading={loading} icon={<ExperimentOutlined />} onClick={runSkill}>运行</Button>}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Select
                value={selectedSkill?.slug}
                placeholder="选择通用技能"
                options={rows.map((row) => ({ value: row.slug, label: `${row.name} / ${row.slug}` }))}
                onChange={setSelectedSlug}
              />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} />
            </Space>
          </Card>
        </Space>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card className="data-card" title="通用技能列表">
            <Table rowKey="id" columns={columns} dataSource={rows} pagination={false} size="middle" />
          </Card>
          <Card className="data-card" title="运行结果">
            {runResult ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Typography.Paragraph className="result-reply">{runResult.reply}</Typography.Paragraph>
                <pre className="debug-panel">{JSON.stringify(runResult.execution_trace, null, 2)}</pre>
                <pre className="debug-panel">{JSON.stringify(runResult.structured_result, null, 2)}</pre>
              </Space>
            ) : (
              <Typography.Text type="secondary">暂无运行结果</Typography.Text>
            )}
          </Card>
        </Space>
      </div>
    </>
  );
}
