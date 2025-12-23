"""
诊治结果可视化模块
提供图形化界面展示农作物病害诊治结果
"""

import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import os


class CropDiseaseVisualizer:
    """
    农作物病害诊治结果可视化界面
    """
    def __init__(self, root, diagnosis_result):
        self.root = root
        self.result = diagnosis_result
        self.root.title("农作物病害诊治结果")
        self.root.geometry("900x700")
        self.root.configure(bg="#f0f0f0")
        
        # 创建主框架
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建结果展示区域
        self.create_result_display()
        
        # 创建图表展示区域
        self.create_charts()
        
        # 创建治疗方案展示区域
        self.create_treatment_plan()
        
    def create_result_display(self):
        """创建结果展示区域"""
        # 标题
        title_label = ttk.Label(
            self.main_frame, 
            text="【农作物病害诊断报告】", 
            font=("Arial", 18, "bold"),
            background="#4CAF50",
            foreground="white",
            padding=(10, 5)
        )
        title_label.pack(fill=tk.X, pady=10)
        
        # 基本信息框架
        info_frame = ttk.LabelFrame(self.main_frame, text="基本信息", padding="10")
        info_frame.pack(fill=tk.X, pady=5)
        
        # 作物类型
        ttk.Label(info_frame, text="作物类型:", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Label(info_frame, text=self.result.get("作物类型", "未识别"), font=("Arial", 12)).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
        
        # 生长阶段
        ttk.Label(info_frame, text="生长阶段:", font=("Arial", 12, "bold")).grid(row=0, column=2, sticky=tk.W, padx=10, pady=5)
        ttk.Label(info_frame, text=self.result.get("生长阶段", "未识别"), font=("Arial", 12)).grid(row=0, column=3, sticky=tk.W, padx=10, pady=5)
        
        # 症状描述
        ttk.Label(info_frame, text="症状描述:", font=("Arial", 12, "bold")).grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        symptoms_text = ", ".join(self.result.get("症状", []))
        ttk.Label(info_frame, text=symptoms_text, font=("Arial", 12)).grid(row=1, column=1, columnspan=3, sticky=tk.W, padx=10, pady=5)
        
        # 诊断结果框架
        diagnosis_frame = ttk.LabelFrame(self.main_frame, text="诊断结果", padding="10")
        diagnosis_frame.pack(fill=tk.X, pady=5)
        
        # 病害类型
        disease_type = self.result.get("病害类型", "未诊断")
        disease_label = ttk.Label(diagnosis_frame, text="病害类型:", font=("Arial", 12, "bold"))
        disease_label.grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        
        # 根据病害类型显示不同颜色
        if disease_type == "健康":
            color = "green"
        else:
            color = "red"
        
        ttk.Label(diagnosis_frame, text=disease_type, font=("Arial", 12), foreground=color).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
        
        # 诊断置信度
        confidence = self.result.get("诊断置信度")
        if confidence:
            ttk.Label(diagnosis_frame, text="置信度:", font=("Arial", 12, "bold")).grid(row=0, column=2, sticky=tk.W, padx=10, pady=5)
            confidence_label = ttk.Label(diagnosis_frame, text=f"{confidence:.2%}", font=("Arial", 12))
            confidence_label.grid(row=0, column=3, sticky=tk.W, padx=10, pady=5)
            
            # 置信度进度条
            progress_var = tk.DoubleVar()
            progress_var.set(confidence * 100)
            progress_bar = ttk.Progressbar(diagnosis_frame, variable=progress_var, maximum=100, length=200)
            progress_bar.grid(row=1, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        
        # 病害描述
        ttk.Label(diagnosis_frame, text="病害描述:", font=("Arial", 12, "bold")).grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        desc_text = tk.Text(diagnosis_frame, height=3, width=80, font=("Arial", 12))
        desc_text.insert(tk.END, self.result.get("病害描述", "无详细描述"))
        desc_text.config(state=tk.DISABLED)
        desc_text.grid(row=2, column=1, columnspan=3, padx=10, pady=5, sticky=tk.EW)
    
    def create_charts(self):
        """创建图表展示区域"""
        chart_frame = ttk.LabelFrame(self.main_frame, text="诊断分析", padding="10")
        chart_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 创建两个子框架
        left_chart_frame = ttk.Frame(chart_frame)
        left_chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        right_chart_frame = ttk.Frame(chart_frame)
        right_chart_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # 诊断置信度饼图
        self.create_confidence_pie(left_chart_frame)
        
        # 病害分布柱状图
        self.create_disease_bar(right_chart_frame)
    
    def create_confidence_pie(self, parent_frame):
        """创建诊断置信度饼图"""
        fig = plt.Figure(figsize=(4, 3), dpi=100)
        ax = fig.add_subplot(111)
        
        confidence = self.result.get("诊断置信度", 0.0)
        
        # 饼图数据
        labels = ['置信度', '不确定性']
        sizes = [confidence, 1 - confidence]
        colors = ['#4CAF50', '#f44336']
        explode = (0.1, 0)  # 突出显示置信度
        
        ax.pie(sizes, explode=explode, labels=labels, colors=colors, 
               autopct='%1.1f%%', shadow=True, startangle=90)
        ax.axis('equal')  # 保持饼图为圆形
        ax.set_title('诊断置信度分析')
        
        # 添加到界面
        canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    def create_disease_bar(self, parent_frame):
        """创建病害分布柱状图"""
        # 这里使用模拟数据，实际应用中可以从模型中获取所有类别的概率
        disease_classes = [
            "健康", "早疫病", "晚疫病", "黄化曲叶病毒病", 
            "叶霉病", "白粉病", "细菌性斑点病", "灰霉病"
        ]
        
        # 生成模拟概率数据
        np.random.seed(42)
        probabilities = np.random.rand(len(disease_classes)) * 0.3
        
        # 设置当前诊断结果的概率
        current_disease = self.result.get("病害类型", "健康")
        if current_disease in disease_classes:
            idx = disease_classes.index(current_disease)
            probabilities[idx] = 1.0 - sum(probabilities) + probabilities[idx]
        
        # 创建柱状图
        fig = plt.Figure(figsize=(4, 3), dpi=100)
        ax = fig.add_subplot(111)
        
        # 设置颜色
        colors = ["#4CAF50" if cls == current_disease else "#9E9E9E" for cls in disease_classes]
        
        bars = ax.bar(disease_classes, probabilities, color=colors)
        
        # 设置标签旋转
        plt.xticks(rotation=45, ha='right', fontsize=8)
        
        # 添加数值标签
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                    f'{height:.2f}', ha='center', va='bottom', fontsize=8)
        
        ax.set_ylabel('概率')
        ax.set_title('病害概率分布')
        ax.set_ylim(0, 1.1)
        
        # 添加到界面
        canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    def create_treatment_plan(self):
        """创建治疗方案展示区域"""
        # 治疗方案框架
        treatment_frame = ttk.LabelFrame(self.main_frame, text="治疗方案与预防建议", padding="10")
        treatment_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 创建两个子框架
        treatment_plan_frame = ttk.Frame(treatment_frame)
        treatment_plan_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        prevention_frame = ttk.Frame(treatment_frame)
        prevention_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # 治疗方案
        ttk.Label(treatment_plan_frame, text="💊 治疗方案", font= ("Arial", 14, "bold")).pack(anchor=tk.W, pady=5)
        treatment_text = tk.Text(treatment_plan_frame, height=10, width=40, font= ("Arial", 12))
        treatment_text.insert("end", str(self.result.get("治疗方案", "暂无治疗方案")))
        treatment_text.config(state=tk.DISABLED, wrap=tk.WORD)
        treatment_text.pack(fill=tk.BOTH, expand=True)
        
        # 预防建议
        ttk.Label(prevention_frame, text="🛡️ 预防建议", font= ("Arial", 14, "bold")).pack(anchor=tk.W, pady=5)
        prevention_text = tk.Text(prevention_frame, height=10, width=40, font= ("Arial", 12))
        prevention_text.insert("end", str(self.result.get("预防建议", "暂无预防建议")))
        prevention_text.config(state=tk.DISABLED, wrap=tk.WORD)
        prevention_text.pack(fill=tk.BOTH, expand=True)
        
        # 按钮框架
        button_frame = ttk.Frame(self.main_frame, padding="10")
        button_frame.pack(fill=tk.X, pady=5)
        
        # 保存按钮
        save_button = ttk.Button(button_frame, text="保存报告", command=self.save_report)
        save_button.pack(side=tk.LEFT, padx=5)
        
        # 关闭按钮
        close_button = ttk.Button(button_frame, text="关闭", command=self.root.destroy)
        close_button.pack(side=tk.RIGHT, padx=5)
    
    def save_report(self):
        """保存诊断报告"""
        # 这里可以实现保存报告的功能，例如保存为PDF或图片
        messagebox.showinfo("保存报告", "报告保存功能已触发！")


def visualize_diagnosis_result(result):
    """
    可视化诊断结果
    
    Args:
        result: 诊断结果字典
    """
    import matplotlib
    import matplotlib.pyplot as plt
    
    # 确保使用正确的交互式后端
    if matplotlib.get_backend() == 'Agg':
        matplotlib.use('TkAgg')  # 切换到Tkinter后端
    
    # 清理可能存在的旧图表
    plt.close('all')
    
    root = tk.Tk()
    
    # 设置窗口关闭时的回调
    def on_close():
        # 清理资源
        plt.close('all')
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    app = CropDiseaseVisualizer(root, result)
    
    # 运行Tkinter主事件循环，直到窗口关闭
    root.mainloop()


if __name__ == "__main__":
    # 测试用例
    test_result = {
        "作物类型": "番茄",
        "生长阶段": "结果期",
        "症状": ["斑点", "腐烂"],
        "病害类型": "晚疫病",
        "诊断置信度": 0.95,
        "病害描述": "晚疫病会导致番茄果实和叶片快速腐烂，病斑呈水渍状，在潮湿环境下发展迅速。",
        "治疗方案": "使用百菌清、代森锰锌或嘧菌酯喷雾，每7-10天一次，连续2-3次。建议在发病初期使用效果最佳。",
        "预防建议": "1. 选用抗病品种\n2. 合理密植，加强通风\n3. 科学施肥，避免偏施氮肥\n4. 及时清除病残体"
    }
    
    visualize_diagnosis_result(test_result)
